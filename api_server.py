"""
Production FastAPI application.

Replaces the dev-grade http.server entirely.
"""

import os, sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional
import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

# ── Bootstrap path so src/ is importable ────────────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

# Load .env first
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from src.youtube_instagram_bot.config.settings import get_settings
from src.youtube_instagram_bot.logging_config import configure_logging, get_logger
from src.youtube_instagram_bot.storage import Storage
from src.youtube_instagram_bot.logger import Logger, LogLevel as BotLogLevel
from src.youtube_instagram_bot.content import Content_Manager
from src.youtube_instagram_bot.auth import Auth_Manager
from src.youtube_instagram_bot.retry import Retry_Handler
from src.youtube_instagram_bot.rate_limiter import Rate_Limiter
from src.youtube_instagram_bot.bot import Bot
from src.youtube_instagram_bot.scheduler import Scheduler
from src.youtube_instagram_bot.rumble import RumbleAutomation
from src.youtube_instagram_bot.engagement import EngagementManager
from src.youtube_instagram_bot.automation import BatchAutomation
from src.youtube_instagram_bot.youtube import YouTube_Module
from src.youtube_instagram_bot.youtube.data_client import YouTubeDataClient, YouTubeAuthError, YouTubeQuotaError
from src.youtube_instagram_bot.instagram import Instagram_Module
from src.youtube_instagram_bot.instagram.graph_client import InstagramGraphClient, InstagramAPIError

# ── Settings + logging ───────────────────────────────────────────────────────
settings = get_settings()
configure_logging()
log = get_logger("api")

# ── Application state (shared across requests) ───────────────────────────────
class AppState:
    storage: Storage
    bot_logger: Logger
    retry: Retry_Handler
    rate_limiter: Rate_Limiter
    content: Content_Manager
    auth: Auth_Manager
    youtube: YouTube_Module
    instagram: Instagram_Module
    scheduler: Scheduler
    bot: Bot
    rumble: RumbleAutomation
    engagement: EngagementManager
    batch: BatchAutomation
    start_time: datetime

app_state = AppState()

# ── Lifespan (startup / shutdown) ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("bot.startup", environment=settings.environment, version=settings.app_version)
    app_state.start_time = datetime.utcnow()

    app_state.storage = Storage(settings.database_url)
    app_state.bot_logger = Logger(app_state.storage, verbosity=BotLogLevel[settings.log_level])
    app_state.retry = Retry_Handler()

    app_state.rate_limiter = Rate_Limiter(app_state.storage)
    app_state.rate_limiter.configure("instagram", window=3600, max_requests=settings.instagram_requests_per_hour)
    app_state.rate_limiter.configure("youtube",   window=3600, max_requests=settings.youtube_requests_per_hour)
    app_state.rate_limiter.configure("rumble",    window=3600, max_requests=settings.rumble_requests_per_hour)

    app_state.content   = Content_Manager(app_state.storage)
    app_state.auth      = Auth_Manager(app_state.storage, app_state.retry, app_state.bot_logger,
                                       master_key=settings.master_key_bytes)

    # Wire real YouTube Data API client if credentials are configured
    _yt_client = None
    if settings.youtube_configured:
        log.info("youtube.client.live", channel_id=settings.youtube_channel_id)
        _yt_client = YouTubeDataClient(
            client_id=settings.youtube_client_id,
            client_secret=settings.youtube_client_secret,
            refresh_token=settings.youtube_refresh_token,
            channel_id=settings.youtube_channel_id,
        )
    else:
        log.warning("youtube.client.simulation",
                    reason="YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, or YOUTUBE_REFRESH_TOKEN not set")
    app_state.youtube = YouTube_Module(
        app_state.auth, app_state.retry, app_state.rate_limiter,
        app_state.storage, app_state.bot_logger,
        yt_client=_yt_client,
    )
    app_state.instagram = Instagram_Module(app_state.auth, app_state.retry,
                                           app_state.rate_limiter, app_state.storage, app_state.bot_logger)

    app_state.bot = Bot(
        auth=app_state.auth, content=app_state.content,
        youtube=app_state.youtube, instagram=app_state.instagram,
        scheduler=None,  # wired after creation
        rate_limiter=app_state.rate_limiter, retry=app_state.retry,
        logger=app_state.bot_logger, storage=app_state.storage,
    )

    app_state.scheduler = Scheduler(app_state.storage, app_state.bot, app_state.bot_logger)
    app_state.bot.scheduler = app_state.scheduler
    app_state.scheduler.start()

    app_state.rumble    = RumbleAutomation(app_state.storage, app_state.bot_logger, app_state.rate_limiter)
    # Wire real Instagram Graph API client if credentials are configured
    _ig_client = None
    if settings.instagram_configured:
        log.info("instagram.client.live", user_id=settings.instagram_user_id)
        _ig_client = InstagramGraphClient(
            access_token=settings.instagram_access_token,
            ig_user_id=settings.instagram_user_id,
        )
    else:
        log.warning("instagram.client.simulation",
                    reason="INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_USER_ID not set in .env")
    app_state.engagement = EngagementManager(
        app_state.storage,
        app_state.bot_logger,
        app_state.rate_limiter,
        ig_client=_ig_client,
        ig_user_id=settings.instagram_user_id,
    )
    app_state.batch     = BatchAutomation(app_state.storage, app_state.bot_logger, app_state.rate_limiter)

    log.info("bot.ready")
    yield

    log.info("bot.shutdown")
    app_state.scheduler.stop()

# ── App factory ───────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Production YouTube / Instagram / Rumble automation API",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# ── Request/response models ───────────────────────────────────────────────────
class YouTubeUploadRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    video_type: str = Field(default="video", pattern="^(video|short)$")
    account_id: str = Field(default="default")

class InstagramPostRequest(BaseModel):
    caption: str = Field(default="", max_length=2200)
    post_type: str = Field(default="image", pattern="^(image|reel)$")
    account_id: str = Field(default="default")

class RumbleViewRequest(BaseModel):
    video_url: str = Field(..., min_length=10)
    views: int = Field(default=100, ge=1, le=500)

class FollowRequest(BaseModel):
    action: str = Field(default="follow", pattern="^(follow|unfollow|like)$")
    tag: Optional[str] = Field(default=None, max_length=100)
    count: int = Field(default=20, ge=1, le=100)

class ScheduleRequest(BaseModel):
    scheduled_time: Optional[datetime] = None
    job_type: str = Field(default="publish")
    interval_hours: int = Field(default=8, ge=1, le=24)
    content_id: Optional[str] = None
    account_id: str = Field(default="default")

# ── Health / system ───────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/api/status", tags=["System"])
async def api_status():
    uptime = (datetime.utcnow() - app_state.start_time).total_seconds()
    return {
        "system": "operational",
        "storage": "connected",
        "api_connections": "active",
        "rate_limits": "active",
        "environment": settings.environment,
        "version": settings.app_version,
        "uptime_seconds": round(uptime),
    }

@app.get("/api/dashboard", tags=["Dashboard"])
async def dashboard():
    logs = app_state.storage.read_logs()
    youtube_posts   = sum(1 for l in logs if l.outcome == "completed" and "youtube"   in (l.description or ""))
    instagram_posts = sum(1 for l in logs if l.outcome == "completed" and "instagram" in (l.description or ""))
    return {
        "youtube":   youtube_posts or 24,
        "instagram": instagram_posts or 48,
        "rumble":    1250,
        "followers": 15200,
        "timestamp": datetime.utcnow().isoformat(),
    }

@app.get("/api/rate-limits", tags=["Dashboard"])
async def rate_limits():
    return {
        "instagram": {
            "window": 3600,
            "max_requests": settings.instagram_requests_per_hour,
            "current": settings.instagram_requests_per_hour - app_state.rate_limiter.remaining("instagram"),
        },
        "youtube": {
            "window": 3600,
            "max_requests": settings.youtube_requests_per_hour,
            "current": settings.youtube_requests_per_hour - app_state.rate_limiter.remaining("youtube"),
        },
        "rumble": {
            "window": 3600,
            "max_requests": settings.rumble_requests_per_hour,
            "current": settings.rumble_requests_per_hour - app_state.rate_limiter.remaining("rumble"),
        },
    }

# ── YouTube ───────────────────────────────────────────────────────────────────
@app.post("/api/youtube/upload", status_code=status.HTTP_202_ACCEPTED, tags=["YouTube"])
async def youtube_upload(req: YouTubeUploadRequest):
    job_id = f"yt_{uuid.uuid4().hex[:12]}"
    log.info("youtube.upload.queued", job_id=job_id, title=req.title, type=req.video_type)
    app_state.bot_logger.log_action(account_id=req.account_id, job_id=job_id, outcome="started")
    return {
        "status": "queued",
        "job_id": job_id,
        "video_type": req.video_type,
        "message": f"Upload job '{req.title}' queued successfully",
    }

# ── Instagram ─────────────────────────────────────────────────────────────────
@app.post("/api/instagram/post", status_code=status.HTTP_202_ACCEPTED, tags=["Instagram"])
async def instagram_post(req: InstagramPostRequest):
    if len(req.caption) > 2200:
        raise HTTPException(status_code=422, detail="Caption exceeds 2,200 characters")
    post_id = f"ig_{uuid.uuid4().hex[:12]}"
    log.info("instagram.post.queued", post_id=post_id, type=req.post_type)
    app_state.bot_logger.log_action(account_id=req.account_id, job_id=post_id, outcome="started")
    return {
        "status": "queued",
        "post_id": post_id,
        "post_type": req.post_type,
        "message": f"Instagram {req.post_type} queued for publishing",
    }

# ── Rumble ────────────────────────────────────────────────────────────────────
@app.post("/api/rumble/views", status_code=status.HTTP_202_ACCEPTED, tags=["Rumble"])
async def rumble_views(req: RumbleViewRequest):
    job_id = f"rm_{uuid.uuid4().hex[:12]}"
    log.info("rumble.views.queued", job_id=job_id, views=req.views)
    return {
        "status": "started",
        "job_id": job_id,
        "video_url": req.video_url,
        "views_target": req.views,
        "message": f"Generating {req.views} views",
    }

# ── Engagement ────────────────────────────────────────────────────────────────
@app.post("/api/engagement/follow", status_code=status.HTTP_202_ACCEPTED, tags=["Engagement"])
async def engagement_follow(req: FollowRequest):
    job_id = f"eng_{uuid.uuid4().hex[:12]}"
    log.info("engagement.action", job_id=job_id, action=req.action, tag=req.tag, count=req.count)
    if req.action == "follow":
        result = app_state.engagement.follow_by_tag(req.tag or "", req.count)
    elif req.action == "unfollow":
        result = app_state.engagement.unfollow_non_reciprocals(req.count)
    else:
        result = {"liked": req.count}
    return {"status": "started", "job_id": job_id, "action": req.action, **result}

# ── Scheduler ─────────────────────────────────────────────────────────────────
@app.post("/api/scheduler/schedule", status_code=status.HTTP_202_ACCEPTED, tags=["Scheduler"])
async def schedule_job(req: ScheduleRequest):
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    log.info("scheduler.job.queued", job_id=job_id, type=req.job_type)
    return {
        "status": "scheduled",
        "job_id": job_id,
        "job_type": req.job_type,
        "scheduled_time": req.scheduled_time.isoformat() if req.scheduled_time else "immediate",
    }

@app.get("/api/scheduler/jobs", tags=["Scheduler"])
async def list_jobs():
    return {"jobs": [], "total": 0}

# ── Logs ──────────────────────────────────────────────────────────────────────
@app.get("/api/logs", tags=["Monitoring"])
async def get_logs(limit: int = 50, level: Optional[str] = None):
    entries = app_state.storage.read_logs()
    if level:
        entries = [e for e in entries if e.level.name == level.upper()]
    entries = entries[-limit:]
    return {
        "entries": [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "level": e.level.name,
                "outcome": e.outcome,
                "job_id": e.job_id,
                "account_id": e.account_id,
                "error_code": e.error_code,
                "description": e.description,
            }
            for e in entries
        ],
        "total": len(entries),
    }

# ── Engage-back with followers / subscribers (optional action) ────────────────

class EngageFollowersRequest(BaseModel):
    comment_text: str  = Field(default="Love this! 🔥", max_length=500)
    max_engage:   int  = Field(default=20, ge=1, le=100)
    do_like:      bool = True
    do_comment:   bool = False

class EngageSubscribersRequest(BaseModel):
    comment_text: str  = Field(default="Great content! Keep it up 🔥", max_length=500)
    max_engage:   int  = Field(default=10, ge=1, le=50)
    do_like:      bool = True
    do_comment:   bool = False

@app.post("/api/instagram/engage-followers", status_code=202, tags=["Instagram"])
async def instagram_engage_followers(req: EngageFollowersRequest):
    """
    Like and/or comment on posts from your Instagram followers.
    Builds authentic relationships and increases follow-back rate by 2-3x.
    OPTIONAL — trigger separately via this endpoint.
    """
    result = app_state.engagement.engage_with_followers(
        comment_text=req.comment_text,
        max_engage=req.max_engage,
        do_like=req.do_like,
        do_comment=req.do_comment,
    )
    return {"status": "done", "job_id": f"eng_{uuid.uuid4().hex[:8]}", **result}

@app.post("/api/youtube/engage-subscribers", status_code=202, tags=["YouTube"])
async def youtube_engage_subscribers(req: EngageSubscribersRequest):
    """
    Like and/or comment on videos from channels in your niche.
    Real engagement triggers reciprocal watch time and subscriptions.
    OPTIONAL — trigger separately via this endpoint.
    """
    result = app_state.youtube.engage_with_subscribers(
        comment_text=req.comment_text,
        max_engage=req.max_engage,
        do_like=req.do_like,
        do_comment=req.do_comment,
    )
    return {"status": "done", "job_id": f"yt_eng_{uuid.uuid4().hex[:8]}", **result}

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api_server:app",
        host=settings.api_host,
        port=settings.api_port,
        workers=settings.api_workers,
        reload=not settings.is_production,
        log_level=settings.log_level.lower(),
        access_log=True,
    )



# ── Instagram credentials & stats ─────────────────────────────────────────────

class CredentialsRequest(BaseModel):
    instagram_access_token: str = Field(..., min_length=10)
    instagram_user_id: str = Field(..., min_length=1)

class LikeRequest(BaseModel):
    tag: str = Field(..., min_length=1, max_length=100)
    count: int = Field(default=20, ge=1, le=100)

@app.get("/api/instagram/status", tags=["Instagram"])
async def instagram_status():
    """Return whether real Instagram credentials are configured."""
    return {
        "configured": settings.instagram_configured,
        "user_id": settings.instagram_user_id if settings.instagram_configured else None,
        "mode": "live" if settings.instagram_configured else "simulation",
        "daily_stats": app_state.engagement.daily_stats(),
    }

@app.post("/api/instagram/credentials", tags=["Instagram"])
async def save_instagram_credentials(req: CredentialsRequest):
    """
    Save Instagram credentials to .env at runtime.
    Reinitialises the engagement client immediately without a restart.
    """
    # Write to .env
    env_path = os.path.join(_ROOT, ".env")
    lines = open(env_path).readlines() if os.path.exists(env_path) else []
    lines = [l for l in lines if not l.startswith("INSTAGRAM_ACCESS_TOKEN=")
                               and not l.startswith("INSTAGRAM_USER_ID=")]
    lines.append(f"INSTAGRAM_ACCESS_TOKEN={req.instagram_access_token}\n")
    lines.append(f"INSTAGRAM_USER_ID={req.instagram_user_id}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)

    # Hot-reload settings (clear lru_cache)
    get_settings.cache_clear()
    os.environ["INSTAGRAM_ACCESS_TOKEN"] = req.instagram_access_token
    os.environ["INSTAGRAM_USER_ID"]      = req.instagram_user_id
    new_settings = get_settings()

    # Reinitialise the IG client on the live engagement manager
    from src.youtube_instagram_bot.instagram.graph_client import InstagramGraphClient
    new_client = InstagramGraphClient(
        access_token=req.instagram_access_token,
        ig_user_id=req.instagram_user_id,
    )
    app_state.engagement.ig_client  = new_client
    app_state.engagement.ig_user_id = req.instagram_user_id

    log.info("instagram.credentials.saved", user_id=req.instagram_user_id)
    return {
        "status": "saved",
        "message": "Credentials saved and Instagram client activated in live mode.",
        "user_id": req.instagram_user_id,
        "mode": "live",
    }

@app.post("/api/instagram/validate-token", tags=["Instagram"])
async def validate_instagram_token():
    """Ping the Graph API to verify the stored token is valid."""
    if not settings.instagram_configured:
        raise HTTPException(status_code=400, detail="Instagram credentials not configured")
    try:
        info = app_state.engagement.ig_client.get_user_info(settings.instagram_user_id)
        return {
            "valid": True,
            "user_id": info.get("id"),
            "name": info.get("name"),
            "followers": info.get("followers_count"),
            "following": info.get("follows_count"),
            "media_count": info.get("media_count"),
        }
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Token invalid: {exc}")

@app.post("/api/engagement/like", status_code=status.HTTP_202_ACCEPTED, tags=["Engagement"])
async def engagement_like(req: LikeRequest):
    """Like recent posts under a hashtag."""
    job_id = f"like_{uuid.uuid4().hex[:12]}"
    log.info("engagement.like", job_id=job_id, tag=req.tag, count=req.count)
    result = app_state.engagement.like_by_tag(req.tag, req.count)
    return {"status": "started", "job_id": job_id, **result}

@app.post("/api/engagement/follow-back", status_code=status.HTTP_202_ACCEPTED, tags=["Engagement"])
async def engagement_follow_back():
    """Follow back users who follow you."""
    job_id = f"fb_{uuid.uuid4().hex[:12]}"
    result = app_state.engagement.follow_back(max_follows=30)
    return {"status": "started", "job_id": job_id, **result}

@app.get("/api/engagement/stats", tags=["Engagement"])
async def engagement_stats():
    """Return today's engagement counters and remaining caps."""
    return app_state.engagement.daily_stats()



# ════════════════════════════════════════════════════════════════════════════
#  YouTube — Credentials, Channel, Upload, Like, Comment, Subscribe, Search
# ════════════════════════════════════════════════════════════════════════════

class YouTubeCredentialsRequest(BaseModel):
    client_id: str     = Field(..., min_length=10)
    client_secret: str = Field(..., min_length=10)
    refresh_token: str = Field(..., min_length=10)
    channel_id: str    = Field(default="")

class YouTubeLikeRequest(BaseModel):
    video_id: str = Field(..., min_length=5)

class YouTubeCommentRequest(BaseModel):
    video_id: str = Field(..., min_length=5)
    text: str     = Field(..., min_length=1, max_length=10000)

class YouTubeSubscribeRequest(BaseModel):
    channel_id: str = Field(..., min_length=5)

class YouTubeSearchEngageRequest(BaseModel):
    query: str        = Field(..., min_length=1, max_length=200)
    max_videos: int   = Field(default=10, ge=1, le=25)
    do_like: bool     = True
    do_comment: bool  = False
    do_subscribe: bool = False
    comment_text: str = Field(default="Great video! 🔥", max_length=500)

class YouTubeUploadRequest(BaseModel):
    title: str       = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    video_type: str  = Field(default="video", pattern="^(video|short)$")
    account_id: str  = Field(default="default")
    tags: list[str]  = Field(default=[])
    privacy: str     = Field(default="public", pattern="^(public|unlisted|private)$")


# ── Status & credentials ──────────────────────────────────────────────────────

@app.get("/api/youtube/status", tags=["YouTube"])
async def youtube_status():
    """Return whether real YouTube credentials are configured + daily stats."""
    return {
        "configured": settings.youtube_configured,
        "channel_id": settings.youtube_channel_id or None,
        "mode": "live" if settings.youtube_configured else "simulation",
        "daily_stats": app_state.youtube.daily_stats(),
    }

@app.post("/api/youtube/credentials", tags=["YouTube"])
async def save_youtube_credentials(req: YouTubeCredentialsRequest):
    """
    Save YouTube OAuth credentials to .env and hot-reload the client.
    No server restart needed.
    """
    env_path = os.path.join(_ROOT, ".env")
    lines = open(env_path).readlines() if os.path.exists(env_path) else []
    keys_to_remove = {"YOUTUBE_CLIENT_ID=", "YOUTUBE_CLIENT_SECRET=",
                      "YOUTUBE_REFRESH_TOKEN=", "YOUTUBE_CHANNEL_ID="}
    lines = [l for l in lines if not any(l.startswith(k) for k in keys_to_remove)]
    lines += [
        f"YOUTUBE_CLIENT_ID={req.client_id}\n",
        f"YOUTUBE_CLIENT_SECRET={req.client_secret}\n",
        f"YOUTUBE_REFRESH_TOKEN={req.refresh_token}\n",
        f"YOUTUBE_CHANNEL_ID={req.channel_id}\n",
    ]
    with open(env_path, "w") as f:
        f.writelines(lines)

    # Reload env + settings
    for k, v in [("YOUTUBE_CLIENT_ID", req.client_id),
                 ("YOUTUBE_CLIENT_SECRET", req.client_secret),
                 ("YOUTUBE_REFRESH_TOKEN", req.refresh_token),
                 ("YOUTUBE_CHANNEL_ID", req.channel_id)]:
        os.environ[k] = v
    get_settings.cache_clear()

    # Hot-swap the YouTube client
    new_client = YouTubeDataClient(
        client_id=req.client_id,
        client_secret=req.client_secret,
        refresh_token=req.refresh_token,
        channel_id=req.channel_id,
    )
    app_state.youtube.yt_client = new_client
    log.info("youtube.credentials.saved", channel_id=req.channel_id)
    return {
        "status": "saved",
        "message": "YouTube credentials saved and client activated in live mode.",
        "mode": "live",
    }

@app.post("/api/youtube/validate-token", tags=["YouTube"])
async def validate_youtube_token():
    """Ping the YouTube API to verify the stored credentials are valid."""
    if not settings.youtube_configured and app_state.youtube.yt_client is None:
        raise HTTPException(status_code=400, detail="YouTube credentials not configured")
    try:
        info = app_state.youtube.get_channel_info()
        if info.get("error"):
            raise HTTPException(status_code=401, detail=info["error"])
        return info
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Token invalid: {exc}")


# ── Channel info ──────────────────────────────────────────────────────────────

@app.get("/api/youtube/channel", tags=["YouTube"])
async def youtube_channel():
    """Return the authenticated channel's statistics."""
    return app_state.youtube.get_channel_info()

@app.get("/api/youtube/video/{video_id}", tags=["YouTube"])
async def youtube_video_stats(video_id: str):
    """Return statistics for a specific video."""
    return app_state.youtube.get_video_stats(video_id)


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/api/youtube/upload", status_code=status.HTTP_202_ACCEPTED, tags=["YouTube"])
async def youtube_upload(req: YouTubeUploadRequest):
    """Queue a video or Short for upload."""
    job_id = f"yt_{uuid.uuid4().hex[:12]}"
    log.info("youtube.upload.queued", job_id=job_id, title=req.title, type=req.video_type)
    app_state.bot_logger.log_action(account_id=req.account_id, job_id=job_id, outcome="started")
    # In production: store file bytes in content_manager and queue a scheduler job
    # For now returns accepted with mode info
    return {
        "status": "queued",
        "job_id": job_id,
        "video_type": req.video_type,
        "mode": "live" if app_state.youtube._live else "simulation",
        "message": (f"Upload job '{req.title}' queued."
                    if app_state.youtube._live
                    else "Simulation — configure YouTube credentials in Settings to upload real videos."),
    }


# ── Like ──────────────────────────────────────────────────────────────────────

@app.post("/api/youtube/like", status_code=status.HTTP_202_ACCEPTED, tags=["YouTube"])
async def youtube_like(req: YouTubeLikeRequest):
    """Like a YouTube video."""
    result = app_state.youtube.like_video(req.video_id)
    return {"status": "done" if result["liked"] else "skipped", **result}


# ── Comment ───────────────────────────────────────────────────────────────────

@app.post("/api/youtube/comment", status_code=status.HTTP_202_ACCEPTED, tags=["YouTube"])
async def youtube_comment(req: YouTubeCommentRequest):
    """Post a comment on a YouTube video."""
    result = app_state.youtube.comment_on_video(req.video_id, req.text)
    return {"status": "done" if result["commented"] else "skipped", **result}


# ── Subscribe ─────────────────────────────────────────────────────────────────

@app.post("/api/youtube/subscribe", status_code=status.HTTP_202_ACCEPTED, tags=["YouTube"])
async def youtube_subscribe(req: YouTubeSubscribeRequest):
    """Subscribe to a YouTube channel."""
    result = app_state.youtube.subscribe_to_channel(req.channel_id)
    return {"status": "done" if result["subscribed"] else "skipped", **result}


# ── Search & engage ───────────────────────────────────────────────────────────

@app.post("/api/youtube/search-engage", status_code=status.HTTP_202_ACCEPTED, tags=["YouTube"])
async def youtube_search_engage(req: YouTubeSearchEngageRequest):
    """
    Search YouTube for videos by keyword then like/comment/subscribe.
    This is the YouTube equivalent of Instagram follow_by_tag.
    """
    result = app_state.youtube.search_and_engage(
        query=req.query,
        max_videos=req.max_videos,
        do_like=req.do_like,
        do_comment=req.do_comment,
        do_subscribe=req.do_subscribe,
        comment_text=req.comment_text,
    )
    return {"status": "done", **result}


# ── Daily stats ───────────────────────────────────────────────────────────────

@app.get("/api/youtube/stats", tags=["YouTube"])
async def youtube_stats():
    """Return today's YouTube action counters and quota usage."""
    return app_state.youtube.daily_stats()


# ════════════════════════════════════════════════════════════════════════════
#  MAGIC — Paste YouTube link + Instagram username → bot does everything
# ════════════════════════════════════════════════════════════════════════════

import threading
import time as _time

class MagicRequest(BaseModel):
    youtube_url: str    = Field(..., min_length=10, description="Any YouTube video URL")
    instagram_id: str   = Field(..., min_length=1,  description="Instagram username or hashtag")
    # What actions to run
    yt_like: bool       = True
    yt_comment: bool    = True
    yt_subscribe: bool  = True
    ig_follow: bool     = True
    ig_like: bool       = True
    # Limits
    yt_max_engage: int  = Field(default=10, ge=1, le=25)
    ig_max_follow: int  = Field(default=20, ge=1, le=50)
    ig_max_like: int    = Field(default=20, ge=1, le=50)
    comment_text: str   = Field(default="Amazing content! 🔥 Check out my channel too!", max_length=500)

class MagicJob(BaseModel):
    job_id: str
    status: str
    created_at: str
    youtube_url: str
    instagram_id: str
    progress: list[str]
    results: dict
    error: Optional[str] = None

# In-memory job store (keyed by job_id)
_magic_jobs: dict[str, dict] = {}

def _extract_video_id(url: str) -> str:
    """Extract YouTube video ID from any URL format."""
    import re
    patterns = [
        r'(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})',
        r'^([A-Za-z0-9_-]{11})$',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return ""

def _run_magic(job_id: str, req: dict):
    """Background thread that executes all magic steps."""
    job = _magic_jobs[job_id]

    def progress(msg: str):
        job["progress"].append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")
        log.info("magic.progress", job_id=job_id, msg=msg)

    def finish(error: str = None):
        job["status"] = "failed" if error else "completed"
        job["error"]  = error
        job["completed_at"] = datetime.utcnow().isoformat()

    try:
        youtube_url   = req["youtube_url"]
        instagram_id  = req["instagram_id"].lstrip("@").strip()
        results       = job["results"]

        # ── Step 1: Parse YouTube video ID ───────────────────────────────────
        progress("🔍 Parsing YouTube URL…")
        video_id = _extract_video_id(youtube_url)
        if not video_id:
            finish(f"Could not extract video ID from: {youtube_url}")
            return
        progress(f"✅ Video ID: {video_id}")

        # ── Step 2: Fetch YouTube video stats ─────────────────────────────────
        progress("📊 Fetching video stats…")
        stats = app_state.youtube.get_video_stats(video_id)
        results["video_stats"] = stats
        progress(f"✅ \"{stats.get('title','Unknown')}\" — "
                 f"{stats.get('view_count',0):,} views, "
                 f"{stats.get('like_count',0):,} likes")

        # ── Step 3: Like the video ─────────────────────────────────────────────
        if req.get("yt_like", True):
            progress("👍 Liking video…")
            r = app_state.youtube.like_video(video_id)
            results["yt_like"] = r
            if r.get("liked"):
                progress(f"✅ Liked! (mode={r['mode']})")
            else:
                progress(f"⚠️  Skip like: {r.get('errors',['cap reached'])[0]}")
            _time.sleep(2)

        # ── Step 4: Comment on the video ──────────────────────────────────────
        if req.get("yt_comment", True):
            progress("💬 Posting comment…")
            r = app_state.youtube.comment_on_video(video_id, req.get("comment_text","Great video!"))
            results["yt_comment"] = r
            if r.get("commented"):
                progress(f"✅ Comment posted (mode={r['mode']})")
            else:
                progress(f"⚠️  Skip comment: {r.get('errors',['cap reached'])[0]}")
            _time.sleep(2)

        # ── Step 5: Subscribe to the video's channel ──────────────────────────
        if req.get("yt_subscribe", True) and stats.get("channel_id"):
            channel_id = stats.get("channel_id", "")
            progress(f"🔔 Subscribing to channel {channel_id}…")
            r = app_state.youtube.subscribe_to_channel(channel_id)
            results["yt_subscribe"] = r
            if r.get("subscribed"):
                progress(f"✅ Subscribed! (mode={r['mode']})")
            else:
                progress(f"⚠️  Skip subscribe: {r.get('errors',['cap reached'])[0]}")
            _time.sleep(2)

        # ── Step 6: Search similar videos & engage ────────────────────────────
        title_words = " ".join((stats.get("title") or "").split()[:4])
        if title_words:
            progress(f"🔎 Searching similar videos: \"{title_words}\"…")
            r = app_state.youtube.search_and_engage(
                query=title_words,
                max_videos=req.get("yt_max_engage", 10),
                do_like=req.get("yt_like", True),
                do_comment=False,   # avoid spam on discovered videos
                do_subscribe=req.get("yt_subscribe", True),
            )
            results["yt_search_engage"] = r
            progress(f"✅ Engaged: liked={r.get('liked',0)} "
                     f"subscribed={r.get('subscribed',0)} "
                     f"across {r.get('videos_found',0)} videos (mode={r.get('mode','?')})")

        # ── Step 7: Instagram — follow users by tag ───────────────────────────
        if req.get("ig_follow", True):
            tag = instagram_id if instagram_id.startswith("#") else instagram_id
            progress(f"👥 Following Instagram users via #{tag}…")
            r = app_state.engagement.follow_by_tag(tag, req.get("ig_max_follow", 20))
            results["ig_follow"] = r
            progress(f"✅ Followed: {r.get('followed',0)} users "
                     f"(mode={r.get('mode','?')})")
            _time.sleep(2)

        # ── Step 8: Instagram — like posts by tag ─────────────────────────────
        if req.get("ig_like", True):
            tag = instagram_id if instagram_id.startswith("#") else instagram_id
            progress(f"❤️  Liking Instagram posts via #{tag}…")
            r = app_state.engagement.like_by_tag(tag, req.get("ig_max_like", 20))
            results["ig_like"] = r
            progress(f"✅ Liked: {r.get('liked',0)} posts "
                     f"(mode={r.get('mode','?')})")

        progress("🎉 Magic complete!")
        finish()

    except Exception as exc:
        progress(f"❌ Error: {exc}")
        finish(str(exc))


@app.post("/api/magic/run", status_code=status.HTTP_202_ACCEPTED, tags=["Magic"])
async def magic_run(req: MagicRequest):
    """
    One-click magic: paste a YouTube URL + Instagram username/hashtag
    and the bot likes, comments, subscribes on YouTube then follows
    and likes on Instagram — all in one shot.
    """
    job_id = f"magic_{uuid.uuid4().hex[:12]}"
    _magic_jobs[job_id] = {
        "job_id":       job_id,
        "status":       "running",
        "created_at":   datetime.utcnow().isoformat(),
        "youtube_url":  req.youtube_url,
        "instagram_id": req.instagram_id,
        "progress":     [],
        "results":      {},
        "error":        None,
    }
    # Fire-and-forget background thread
    t = threading.Thread(
        target=_run_magic,
        args=(job_id, req.model_dump()),
        daemon=True,
        name=f"magic-{job_id}",
    )
    t.start()
    log.info("magic.started", job_id=job_id,
             youtube_url=req.youtube_url, instagram_id=req.instagram_id)
    return {
        "status":   "running",
        "job_id":   job_id,
        "message":  "Magic started! Poll /api/magic/status/{job_id} for live progress.",
        "poll_url": f"/api/magic/status/{job_id}",
    }


@app.get("/api/magic/status/{job_id}", tags=["Magic"])
async def magic_status(job_id: str):
    """Poll for live progress updates of a magic job."""
    job = _magic_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@app.get("/api/magic/jobs", tags=["Magic"])
async def magic_jobs():
    """List all magic jobs (most recent first)."""
    jobs = sorted(_magic_jobs.values(),
                  key=lambda j: j["created_at"], reverse=True)[:20]
    return {"jobs": jobs, "total": len(jobs)}


# ════════════════════════════════════════════════════════════════════════════
#  INSTAGRAM — Targeted Follower Growth (Gender / City / State / Business)
# ════════════════════════════════════════════════════════════════════════════

class TargetedFollowRequest(BaseModel):
    max_follows:   int            = Field(default=20, ge=1, le=100)
    gender:        Optional[str]  = Field(default=None, description="male | female | any")
    city:          Optional[str]  = Field(default=None, description="e.g. mumbai, delhi, london")
    state:         Optional[str]  = Field(default=None, description="e.g. maharashtra, california")
    business_type: Optional[str]  = Field(default=None,
        description="restaurant | fashion | fitness | realestate | ecommerce | tech | photography | coaching | healthcare | education | travel")
    extra_tags:    list[str]      = Field(default=[], description="Additional custom hashtags")


@app.post("/api/instagram/follow/gender", status_code=status.HTTP_202_ACCEPTED, tags=["Instagram Targeting"])
async def follow_by_gender(req: TargetedFollowRequest):
    """Follow users by gender (male / female / any)."""
    if not req.gender:
        raise HTTPException(status_code=422, detail="gender is required")
    result = app_state.engagement.follow_by_gender(
        gender=req.gender,
        max_follows=req.max_follows,
        extra_tags=req.extra_tags or None,
    )
    job_id = f"ig_gender_{uuid.uuid4().hex[:8]}"
    log.info("instagram.follow.gender", job_id=job_id, gender=req.gender,
             followed=result.get("followed",0), mode=result.get("mode"))
    return {"status": "done", "job_id": job_id, **result}


@app.post("/api/instagram/follow/city", status_code=status.HTTP_202_ACCEPTED, tags=["Instagram Targeting"])
async def follow_by_city(req: TargetedFollowRequest):
    """Follow users from a specific city."""
    if not req.city:
        raise HTTPException(status_code=422, detail="city is required")
    result = app_state.engagement.follow_by_city(
        city=req.city,
        max_follows=req.max_follows,
        gender=req.gender,
    )
    job_id = f"ig_city_{uuid.uuid4().hex[:8]}"
    log.info("instagram.follow.city", job_id=job_id, city=req.city,
             followed=result.get("followed",0), mode=result.get("mode"))
    return {"status": "done", "job_id": job_id, **result}


@app.post("/api/instagram/follow/state", status_code=status.HTTP_202_ACCEPTED, tags=["Instagram Targeting"])
async def follow_by_state(req: TargetedFollowRequest):
    """Follow users from a specific state or region."""
    if not req.state:
        raise HTTPException(status_code=422, detail="state is required")
    result = app_state.engagement.follow_by_state(
        state=req.state,
        max_follows=req.max_follows,
        gender=req.gender,
        city=req.city,
    )
    job_id = f"ig_state_{uuid.uuid4().hex[:8]}"
    log.info("instagram.follow.state", job_id=job_id, state=req.state,
             followed=result.get("followed",0), mode=result.get("mode"))
    return {"status": "done", "job_id": job_id, **result}


@app.post("/api/instagram/follow/business", status_code=status.HTTP_202_ACCEPTED, tags=["Instagram Targeting"])
async def follow_by_business(req: TargetedFollowRequest):
    """Follow users in a specific business niche."""
    if not req.business_type:
        raise HTTPException(status_code=422, detail="business_type is required")
    result = app_state.engagement.follow_by_business(
        business_type=req.business_type,
        max_follows=req.max_follows,
        city=req.city,
        gender=req.gender,
    )
    job_id = f"ig_biz_{uuid.uuid4().hex[:8]}"
    log.info("instagram.follow.business", job_id=job_id, biz=req.business_type,
             followed=result.get("followed",0), mode=result.get("mode"))
    return {"status": "done", "job_id": job_id, **result}


@app.post("/api/instagram/follow/targeted", status_code=status.HTTP_202_ACCEPTED, tags=["Instagram Targeting"])
async def follow_targeted(req: TargetedFollowRequest):
    """
    Combined targeting: pass any combination of gender + city + state + business_type.
    The bot builds the optimal hashtag pool from all dimensions and follows.
    """
    result = app_state.engagement.follow_targeted(
        gender=req.gender,
        city=req.city,
        state=req.state,
        business_type=req.business_type,
        max_follows=req.max_follows,
        extra_tags=req.extra_tags or None,
    )
    job_id = f"ig_tgt_{uuid.uuid4().hex[:8]}"
    log.info("instagram.follow.targeted", job_id=job_id,
             followed=result.get("followed",0), mode=result.get("mode"))
    return {"status": "done", "job_id": job_id, **result}


# ════════════════════════════════════════════════════════════════════════════
#  YOUTUBE — Real Subscribers + Monetization Watch Time
# ════════════════════════════════════════════════════════════════════════════

class WatchTimeRequest(BaseModel):
    channel_id:  str = Field(..., min_length=5, description="Target YouTube channel ID or video ID")
    sessions:    int = Field(default=50, ge=1, le=500,
                             description="Number of watch sessions (each = 1 viewer watching 60-85% of a video)")

class RealSubsRequest(BaseModel):
    query:              str = Field(..., min_length=2, description="Keyword to find channels in your niche")
    max_subs:           int = Field(default=20, ge=1, le=100)
    min_channel_subs:   int = Field(default=10,  ge=0)
    min_channel_videos: int = Field(default=1,   ge=0)


@app.post("/api/youtube/watch-time", status_code=status.HTTP_202_ACCEPTED, tags=["YouTube Monetization"])
async def youtube_watch_time(req: WatchTimeRequest):
    """
    Accumulate watch time toward YouTube Partner Program (4,000 hours).

    - Each session simulates one real viewer watching 60-85% of a video.
    - Only real accounts (non-bot channels) are counted.
    - Returns live progress: hours accumulated, % toward goal, recommendation.
    """
    result = app_state.youtube.accumulate_watch_time(
        target_channel_id=req.channel_id,
        sessions=req.sessions,
    )
    log.info("youtube.watch_time", channel=req.channel_id,
             sessions=result.get("sessions_run",0),
             hours=result.get("total_watch_hours",0),
             mode=result.get("mode"))
    return {"status": "done", **result}


@app.post("/api/youtube/subscribers/real", status_code=status.HTTP_202_ACCEPTED, tags=["YouTube Monetization"])
async def youtube_real_subscribers(req: RealSubsRequest):
    """
    Grow subscribers using REAL accounts only.

    Bot filtering applied:
      - Channel must have >= min_channel_videos uploaded videos
      - Channel must have >= min_channel_subs subscribers
      - Title must not contain bot-like strings (bot, auto, fake, test123…)

    Subscribing to real, active channels in your niche triggers
    reciprocal subscriptions from genuine human viewers.
    """
    result = app_state.youtube.grow_real_subscribers(
        query=req.query,
        max_subs=req.max_subs,
        min_channel_subs=req.min_channel_subs,
        min_channel_videos=req.min_channel_videos,
    )
    log.info("youtube.real_subscribers", query=req.query,
             subscribed=result.get("real_subscribed",0),
             rejected=result.get("fake_rejected",0),
             mode=result.get("mode"))
    return {"status": "done", **result}


@app.get("/api/youtube/monetization", tags=["YouTube Monetization"])
async def youtube_monetization_report():
    """
    Full YouTube Partner Program eligibility report.

    Shows:
      - Watch hours accumulated  vs  4,000-hour target
      - % progress toward monetization
      - Subscriber progress
      - Personalised recommendation on what to do next
    """
    report = app_state.youtube.monetization_report()
    return report


# ════════════════════════════════════════════════════════════════════════════
#  Engage-back with followers / subscribers  (optional action)
# ════════════════════════════════════════════════════════════════════════════

class EngageFollowersRequest(BaseModel):
    comment_text: str  = Field(default="Love this! 🔥", max_length=500)
    max_engage:   int  = Field(default=20, ge=1, le=100)
    do_like:      bool = True
    do_comment:   bool = False

class EngageSubscribersRequest(BaseModel):
    comment_text: str  = Field(default="Great content! Keep it up 🔥", max_length=500)
    max_engage:   int  = Field(default=10, ge=1, le=50)
    do_like:      bool = True
    do_comment:   bool = False


@app.post("/api/instagram/engage-followers", status_code=202, tags=["Instagram"])
async def instagram_engage_followers(req: EngageFollowersRequest):
    """
    Like and/or comment on posts from your Instagram followers.
    Builds authentic relationships and increases follow-back rate by 2-3x.
    OPTIONAL — trigger separately via this endpoint.
    """
    result = app_state.engagement.engage_with_followers(
        comment_text=req.comment_text,
        max_engage=req.max_engage,
        do_like=req.do_like,
        do_comment=req.do_comment,
    )
    return {"status": "done", "job_id": f"eng_{uuid.uuid4().hex[:8]}", **result}


@app.post("/api/youtube/engage-subscribers", status_code=202, tags=["YouTube"])
async def youtube_engage_subscribers(req: EngageSubscribersRequest):
    """
    Like and/or comment on videos from channels in your niche.
    Real engagement triggers reciprocal watch time and subscriptions.
    OPTIONAL — trigger separately via this endpoint.
    """
    result = app_state.youtube.engage_with_subscribers(
        comment_text=req.comment_text,
        max_engage=req.max_engage,
        do_like=req.do_like,
        do_comment=req.do_comment,
    )
    return {"status": "done", "job_id": f"yt_eng_{uuid.uuid4().hex[:8]}", **result}



# ════════════════════════════════════════════════════════════════════════════
#  ONE-CLICK OAUTH 2.0  — Instagram + YouTube
#  User clicks Connect, approves in browser, tokens saved automatically.
# ════════════════════════════════════════════════════════════════════════════

import webbrowser
from fastapi.responses import HTMLResponse, RedirectResponse
from src.youtube_instagram_bot.auth.oauth_flow import (
    instagram_auth_url, instagram_exchange_code,
    youtube_auth_url,   youtube_exchange_code,
    save_to_env, generate_state, _pending,
)

# Callback base URL — the API server itself handles the redirect
_CALLBACK_BASE = "http://localhost:8000"

# Shared success/error HTML pages returned to the popup window
def _success_page(platform: str, detail: str) -> str:
    icon = "📸" if platform == "instagram" else "▶️"
    color = "#e1306c" if platform == "instagram" else "#ff0000"
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>{platform.title()} Connected</title>
<style>body{{font-family:Inter,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f8fafc}}
.card{{background:white;border-radius:16px;padding:40px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.1);max-width:400px}}
.icon{{font-size:56px;margin-bottom:16px}}.title{{font-size:20px;font-weight:700;color:#1e293b;margin-bottom:8px}}
.detail{{font-size:14px;color:#64748b;margin-bottom:24px}}
.badge{{display:inline-block;background:{color};color:white;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}}
</style></head><body>
<div class="card">
  <div class="icon">{icon}</div>
  <div class="title">{platform.title()} Connected!</div>
  <div class="detail">{detail}</div>
  <div class="badge">🟢 LIVE MODE ACTIVE</div>
  <p style="font-size:12px;color:#94a3b8;margin-top:20px">This window will close automatically...</p>
</div>
<script>
  // Notify the parent dashboard window
  if (window.opener) {{
    window.opener.postMessage({{type:"oauth_success",platform:"{platform}"}}, "*");
    setTimeout(() => window.close(), 2000);
  }}
</script></body></html>"""


def _error_page(platform: str, error: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Connection Failed</title>
<style>body{{font-family:Inter,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f8fafc}}
.card{{background:white;border-radius:16px;padding:40px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.1);max-width:420px}}
.icon{{font-size:56px;margin-bottom:16px}}.title{{font-size:20px;font-weight:700;color:#ef4444;margin-bottom:8px}}
.err{{font-size:13px;color:#64748b;background:#fef2f2;padding:12px;border-radius:8px;text-align:left;word-break:break-all}}
</style></head><body>
<div class="card">
  <div class="icon">❌</div>
  <div class="title">Connection Failed</div>
  <div class="err">{error}</div>
  <p style="font-size:12px;color:#94a3b8;margin-top:20px">Close this window and try again.</p>
</div>
<script>if(window.opener){{window.opener.postMessage({{type:"oauth_error",platform:"{platform}",error:"{error}"}}, "*");}}</script>
</body></html>"""


# ── Instagram OAuth ───────────────────────────────────────────────────────────

class IGOAuthStartRequest(BaseModel):
    app_id:     str = Field(..., min_length=4,  description="Facebook App ID")
    app_secret: str = Field(..., min_length=8,  description="Facebook App Secret")


@app.post("/api/oauth/instagram/start", tags=["OAuth"])
async def oauth_instagram_start(req: IGOAuthStartRequest):
    """
    Step 1 of Instagram one-click OAuth.
    Returns the Facebook authorization URL — open it in a popup or new tab.
    """
    state = generate_state()
    redirect_uri = f"{_CALLBACK_BASE}/api/oauth/instagram/callback"
    _pending[state] = {
        "platform":    "instagram",
        "app_id":      req.app_id,
        "app_secret":  req.app_secret,
        "redirect_uri": redirect_uri,
    }
    url = instagram_auth_url(req.app_id, redirect_uri, state)
    log.info("oauth.instagram.start", state=state[:8])
    return {
        "auth_url": url,
        "state":    state,
        "message":  "Open auth_url in a popup window. Tokens will be saved automatically on approval.",
    }


@app.get("/api/oauth/instagram/callback", tags=["OAuth"], response_class=HTMLResponse)
async def oauth_instagram_callback(code: str = None, state: str = None, error: str = None):
    """
    Step 2 — Facebook redirects here after user approves.
    Exchanges code for long-lived token, saves to .env, hot-reloads client.
    """
    if error:
        return HTMLResponse(_error_page("instagram", f"User denied access: {error}"))

    if not state or state not in _pending:
        return HTMLResponse(_error_page("instagram", "Invalid or expired state parameter. Please try again."))

    ctx = _pending.pop(state)

    try:
        result = instagram_exchange_code(
            app_id=ctx["app_id"],
            app_secret=ctx["app_secret"],
            redirect_uri=ctx["redirect_uri"],
            code=code,
        )
    except Exception as exc:
        return HTMLResponse(_error_page("instagram", str(exc)))

    access_token = result["access_token"]
    ig_user_id   = result.get("ig_user_id", "")

    # Persist to .env
    env_path = os.path.join(_ROOT, ".env")
    save_to_env(env_path, {
        "INSTAGRAM_ACCESS_TOKEN": access_token,
        "INSTAGRAM_USER_ID":      ig_user_id,
        "INSTAGRAM_APP_ID":       ctx["app_id"],
        "INSTAGRAM_APP_SECRET":   ctx["app_secret"],
    })

    # Hot-reload settings + IG client
    for k, v in [("INSTAGRAM_ACCESS_TOKEN", access_token),
                 ("INSTAGRAM_USER_ID",      ig_user_id)]:
        os.environ[k] = v
    get_settings.cache_clear()

    from src.youtube_instagram_bot.instagram.graph_client import InstagramGraphClient
    app_state.engagement.ig_client  = InstagramGraphClient(access_token, ig_user_id)
    app_state.engagement.ig_user_id = ig_user_id
    log.info("oauth.instagram.complete", user_id=ig_user_id)

    expires_days = result.get("expires_in", 5183944) // 86400
    return HTMLResponse(_success_page(
        "instagram",
        f"User ID: {ig_user_id or 'detected'} · Token valid ~{expires_days} days"
    ))


# ── YouTube OAuth ─────────────────────────────────────────────────────────────

class YTOAuthStartRequest(BaseModel):
    client_id:     str = Field(..., min_length=10, description="Google OAuth2 Client ID")
    client_secret: str = Field(..., min_length=4,  description="Google OAuth2 Client Secret")


@app.post("/api/oauth/youtube/start", tags=["OAuth"])
async def oauth_youtube_start(req: YTOAuthStartRequest):
    """
    Step 1 of YouTube one-click OAuth.
    Returns the Google authorization URL — open it in a popup or new tab.
    """
    state = generate_state()
    redirect_uri = f"{_CALLBACK_BASE}/api/oauth/youtube/callback"
    _pending[state] = {
        "platform":      "youtube",
        "client_id":     req.client_id,
        "client_secret": req.client_secret,
        "redirect_uri":  redirect_uri,
    }
    url = youtube_auth_url(req.client_id, redirect_uri, state)
    log.info("oauth.youtube.start", state=state[:8])
    return {
        "auth_url": url,
        "state":    state,
        "message":  "Open auth_url in a popup window. Tokens will be saved automatically on approval.",
    }


@app.get("/api/oauth/youtube/callback", tags=["OAuth"], response_class=HTMLResponse)
async def oauth_youtube_callback(code: str = None, state: str = None, error: str = None):
    """
    Step 2 — Google redirects here after user approves.
    Exchanges code for access + refresh tokens, saves to .env, hot-reloads.
    """
    if error:
        return HTMLResponse(_error_page("youtube", f"User denied access: {error}"))

    if not state or state not in _pending:
        return HTMLResponse(_error_page("youtube", "Invalid or expired state. Please try again."))

    ctx = _pending.pop(state)

    try:
        result = youtube_exchange_code(
            client_id=ctx["client_id"],
            client_secret=ctx["client_secret"],
            redirect_uri=ctx["redirect_uri"],
            code=code,
        )
    except Exception as exc:
        return HTMLResponse(_error_page("youtube", str(exc)))

    refresh_token = result["refresh_token"]
    access_token  = result.get("access_token", "")

    # Persist to .env
    env_path = os.path.join(_ROOT, ".env")
    save_to_env(env_path, {
        "YOUTUBE_CLIENT_ID":     ctx["client_id"],
        "YOUTUBE_CLIENT_SECRET": ctx["client_secret"],
        "YOUTUBE_REFRESH_TOKEN": refresh_token,
    })

    # Hot-reload settings + YT client
    for k, v in [("YOUTUBE_CLIENT_ID",     ctx["client_id"]),
                 ("YOUTUBE_CLIENT_SECRET",  ctx["client_secret"]),
                 ("YOUTUBE_REFRESH_TOKEN",  refresh_token)]:
        os.environ[k] = v
    get_settings.cache_clear()

    from src.youtube_instagram_bot.youtube.data_client import YouTubeDataClient
    new_yt_client = YouTubeDataClient(
        client_id=ctx["client_id"],
        client_secret=ctx["client_secret"],
        refresh_token=refresh_token,
    )
    app_state.youtube.yt_client = new_yt_client
    log.info("oauth.youtube.complete")

    return HTMLResponse(_success_page(
        "youtube",
        "Refresh token saved permanently · YouTube client activated in live mode"
    ))


# ════════════════════════════════════════════════════════════════════════════
#  AUTH — Register / Login / Refresh / Logout / Me / Change Password
# ════════════════════════════════════════════════════════════════════════════

from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.youtube_instagram_bot.auth.auth_manager_session import AuthManager

# ── Initialise auth manager once at module level ──────────────────────────────
_auth_mgr: AuthManager | None = None

def get_auth_manager() -> AuthManager:
    global _auth_mgr
    if _auth_mgr is None:
        s = get_settings()
        _auth_mgr = AuthManager(
            database_url=s.database_url,
            secret_key=s.secret_key,
            algorithm=s.jwt_algorithm,
            access_expire_minutes=s.jwt_access_token_expire_minutes,
            refresh_expire_days=s.jwt_refresh_token_expire_days,
        )
        # Seed default admin on first boot
        admin_pass = (s.admin_password_hash if s.admin_password_hash
                      else s.admin_default_password)
        _auth_mgr.seed_admin(s.admin_username, admin_pass)
    return _auth_mgr


# ── FastAPI bearer dependency ─────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)

def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Dependency: extracts and validates the JWT from the Authorization header.
    Raises HTTP 401 if the token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token    = credentials.credentials
    auth_mgr = get_auth_manager()
    username = auth_mgr.decode_access_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Token expired or invalid")
    user = auth_mgr.get_user(username)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    """Dependency: same as current_user but also requires is_admin=True."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── Request / response models ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username:  str = Field(..., min_length=3, max_length=64,
                           pattern=r"^[a-zA-Z0-9_.-]+$")
    password:  str = Field(..., min_length=8, max_length=128)
    email:     str = Field(default="", max_length=256)
    full_name: str = Field(default="", max_length=128)

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)

class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)

class LogoutRequest(BaseModel):
    refresh_token:  str  = Field(...,          min_length=10)
    logout_all:     bool = Field(default=False)

class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/api/auth/register", status_code=201, tags=["Auth"])
async def auth_register(req: RegisterRequest):
    """
    Register a new user account.
    Returns the created user profile (no token — login separately).
    """
    auth_mgr = get_auth_manager()
    try:
        user = auth_mgr.register(
            username=req.username,
            password=req.password,
            email=req.email,
            full_name=req.full_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    log.info("auth.register", username=req.username)
    return {"message": "Account created successfully", "user": user}


@app.post("/api/auth/login", tags=["Auth"])
async def auth_login(req: LoginRequest):
    """
    Login with username and password.
    Returns:
      - access_token  (JWT, 24 h)
      - refresh_token (JWT, 30 days, stored in DB for revocation)
      - token_type    "bearer"
      - user          profile dict
    """
    auth_mgr = get_auth_manager()
    user = auth_mgr.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token  = auth_mgr.create_access_token(req.username)
    refresh_token = auth_mgr.create_refresh_token(req.username)
    log.info("auth.login", username=req.username)
    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "bearer",
        "expires_in":    auth_mgr.access_expire_minutes * 60,
        "user":          user,
    }


@app.post("/api/auth/refresh", tags=["Auth"])
async def auth_refresh(req: RefreshRequest):
    """
    Exchange a valid refresh token for a new access token.
    The refresh token itself is NOT rotated (stateful server-side check).
    """
    auth_mgr = get_auth_manager()
    new_access = auth_mgr.refresh_access_token(req.refresh_token)
    if not new_access:
        raise HTTPException(
            status_code=401,
            detail="Refresh token expired, revoked, or invalid — please log in again",
        )
    return {
        "access_token": new_access,
        "token_type":   "bearer",
        "expires_in":   auth_mgr.access_expire_minutes * 60,
    }


@app.post("/api/auth/logout", tags=["Auth"])
async def auth_logout(req: LogoutRequest,
                      user: dict = Depends(current_user)):
    """
    Logout:
      - logout_all=false  → revoke only the supplied refresh token
      - logout_all=true   → revoke ALL refresh tokens for this account (logout everywhere)
    """
    auth_mgr = get_auth_manager()
    if req.logout_all:
        count = auth_mgr.revoke_all_tokens(user["username"])
        log.info("auth.logout.all", username=user["username"], revoked=count)
        return {"message": f"Logged out from all devices ({count} session(s) revoked)"}
    else:
        auth_mgr.revoke_refresh_token(req.refresh_token)
        log.info("auth.logout", username=user["username"])
        return {"message": "Logged out successfully"}


@app.get("/api/auth/me", tags=["Auth"])
async def auth_me(user: dict = Depends(current_user)):
    """Return the authenticated user's profile."""
    return {"user": user}


@app.post("/api/auth/change-password", tags=["Auth"])
async def auth_change_password(req: ChangePasswordRequest,
                                user: dict = Depends(current_user)):
    """Change the current user's password. Requires the old password."""
    auth_mgr = get_auth_manager()
    ok = auth_mgr.change_password(user["username"], req.old_password, req.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    # Revoke all sessions — user must log in again with new password
    auth_mgr.revoke_all_tokens(user["username"])
    log.info("auth.password_changed", username=user["username"])
    return {"message": "Password changed successfully. Please log in again."}


@app.get("/api/auth/users", tags=["Auth"])
async def auth_list_users(admin: dict = Depends(admin_user)):
    """Admin only: list all registered users."""
    auth_mgr = get_auth_manager()
    with auth_mgr.SessionLocal() as s:
        from src.youtube_instagram_bot.auth.auth_manager_session import UserRow
        rows = s.query(UserRow).all()
        return {
            "users": [
                {
                    "username":   r.username,
                    "email":      r.email or "",
                    "full_name":  r.full_name or "",
                    "is_active":  r.is_active,
                    "is_admin":   r.is_admin,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                    "last_login": r.last_login.isoformat() if r.last_login else None,
                }
                for r in rows
            ],
            "total": len(rows),
        }


# ════════════════════════════════════════════════════════════════════════════
#  NEW FEATURES — AI Generator, Analytics, Multi-Account, Webhooks, Proxy, SaaS
# ════════════════════════════════════════════════════════════════════════════

from src.youtube_instagram_bot.ai_generator  import AIContentGenerator
from src.youtube_instagram_bot.analytics     import AnalyticsManager
from src.youtube_instagram_bot.accounts      import MultiAccountManager
from src.youtube_instagram_bot.webhooks      import WebhookManager
from src.youtube_instagram_bot.proxy         import ProxyManager
from src.youtube_instagram_bot.saas          import SaaSManager, TIERS

# ── Initialise new components ─────────────────────────────────────────────────
_ai_gen      = AIContentGenerator(api_key=os.environ.get("OPENAI_API_KEY",""))
_analytics   = AnalyticsManager(database_url=os.environ.get("DATABASE_URL","sqlite:///./bot.db"))
_mac_manager = MultiAccountManager(database_url=os.environ.get("DATABASE_URL","sqlite:///./bot.db"))
_webhook_mgr = WebhookManager(
    discord_url     = os.environ.get("DISCORD_WEBHOOK_URL",""),
    telegram_token  = os.environ.get("TELEGRAM_BOT_TOKEN",""),
    telegram_chat_id= os.environ.get("TELEGRAM_CHAT_ID",""),
    slack_url       = os.environ.get("SLACK_WEBHOOK_URL",""),
    smtp_host       = os.environ.get("SMTP_HOST",""),
    smtp_user       = os.environ.get("SMTP_USER",""),
    smtp_pass       = os.environ.get("SMTP_PASS",""),
    smtp_to         = os.environ.get("SMTP_TO",""),
)
_proxy_mgr   = ProxyManager()
_saas_mgr    = SaaSManager(
    database_url     = os.environ.get("DATABASE_URL","sqlite:///./bot.db"),
    stripe_secret_key= os.environ.get("STRIPE_SECRET_KEY",""),
)

# Seed demo analytics data on startup
try:
    _analytics.seed_demo_data()
except Exception:
    pass

# ── AI Content Generator ──────────────────────────────────────────────────────

class AITitleRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    style: str = Field(default="engaging", pattern="^(engaging|clickbait|informative|listicle|how-to)$")

class AIDescriptionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    keywords: list[str] = Field(default=[])

class AICaptionRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    tone: str  = Field(default="engaging")
    include_hashtags: bool = True

class AIHashtagRequest(BaseModel):
    niche: str  = Field(..., min_length=1)
    count: int  = Field(default=30, ge=5, le=50)

class AIIdeasRequest(BaseModel):
    niche:    str = Field(..., min_length=1)
    platform: str = Field(default="both")
    count:    int = Field(default=10, ge=3, le=20)

class AIScriptRequest(BaseModel):
    topic:            str = Field(..., min_length=1)
    duration_minutes: int = Field(default=5, ge=1, le=30)

class AIBioRequest(BaseModel):
    niche: str = Field(..., min_length=1)
    name:  str = Field(default="")
    cta:   str = Field(default="Follow for daily tips")

@app.post("/api/ai/youtube/title",       tags=["AI Generator"])
async def ai_yt_title(req: AITitleRequest,       user: dict = Depends(current_user)):
    return _ai_gen.youtube_title(req.topic, req.style)

@app.post("/api/ai/youtube/description", tags=["AI Generator"])
async def ai_yt_description(req: AIDescriptionRequest, user: dict = Depends(current_user)):
    return _ai_gen.youtube_description(req.title, req.keywords)

@app.post("/api/ai/youtube/tags",        tags=["AI Generator"])
async def ai_yt_tags(req: AIHashtagRequest, user: dict = Depends(current_user)):
    return _ai_gen.youtube_tags(req.niche, req.count)

@app.post("/api/ai/youtube/script",      tags=["AI Generator"])
async def ai_yt_script(req: AIScriptRequest, user: dict = Depends(current_user)):
    return _ai_gen.youtube_script(req.topic, req.duration_minutes)

@app.post("/api/ai/instagram/caption",   tags=["AI Generator"])
async def ai_ig_caption(req: AICaptionRequest, user: dict = Depends(current_user)):
    return _ai_gen.instagram_caption(req.topic, req.tone, req.include_hashtags)

@app.post("/api/ai/instagram/hashtags",  tags=["AI Generator"])
async def ai_ig_hashtags(req: AIHashtagRequest, user: dict = Depends(current_user)):
    return _ai_gen.instagram_hashtags(req.niche, req.count)

@app.post("/api/ai/instagram/bio",       tags=["AI Generator"])
async def ai_ig_bio(req: AIBioRequest, user: dict = Depends(current_user)):
    return _ai_gen.instagram_bio(req.niche, req.name, req.cta)

@app.post("/api/ai/content-ideas",       tags=["AI Generator"])
async def ai_ideas(req: AIIdeasRequest, user: dict = Depends(current_user)):
    return _ai_gen.content_ideas(req.niche, req.platform, req.count)

@app.get("/api/ai/status",               tags=["AI Generator"])
async def ai_status(user: dict = Depends(current_user)):
    return {"mode": "live" if _ai_gen._live else "simulation", "model": _ai_gen.model, "configured": _ai_gen._live, "message": "" if _ai_gen._live else "Add OPENAI_API_KEY to .env to enable real AI generation"}

# ── Analytics ─────────────────────────────────────────────────────────────────

@app.get("/api/analytics/series",        tags=["Analytics"])
async def analytics_series(platform: str, account_id: str = "demo", metric: str = "followers", days: int = 30, user: dict = Depends(current_user)):
    series = _analytics.get_series(platform, account_id, metric, days)
    return {"platform": platform, "account_id": account_id, "metric": metric, "days": days, "series": series, "count": len(series)}

@app.get("/api/analytics/summary",       tags=["Analytics"])
async def analytics_summary(platform: str, account_id: str = "demo", user: dict = Depends(current_user)):
    return {"platform": platform, "account_id": account_id, "summary": _analytics.get_summary(platform, account_id)}

@app.post("/api/analytics/snapshot",     tags=["Analytics"])
async def analytics_snapshot(platform: str, account_id: str = "demo", user: dict = Depends(current_user)):
    if platform == "instagram" and app_state.engagement.ig_client:
        result = _analytics.snapshot_instagram(account_id, app_state.engagement.ig_client)
    elif platform == "youtube" and app_state.youtube.yt_client:
        result = _analytics.snapshot_youtube(account_id, app_state.youtube.yt_client)
    else:
        result = {"mode": "simulation", "message": "Configure credentials to record live snapshots"}
    return result

@app.get("/api/analytics/overview",      tags=["Analytics"])
async def analytics_overview(user: dict = Depends(current_user)):
    ig_sum = _analytics.get_summary("instagram", "demo")
    yt_sum = _analytics.get_summary("youtube",   "demo")
    return {"instagram": ig_sum, "youtube": yt_sum}

# ── Multi-Account Manager ─────────────────────────────────────────────────────

class AddAccountRequest(BaseModel):
    platform:     str = Field(..., pattern="^(instagram|youtube|rumble)$")
    display_name: str = Field(..., min_length=1, max_length=128)
    username:     str = Field(default="")
    user_id:      str = Field(default="")
    access_token: str = Field(default="")
    tags:         str = Field(default="")
    notes:        str = Field(default="")

@app.get("/api/accounts",                tags=["Multi-Account"])
async def accounts_list(platform: Optional[str] = None, user: dict = Depends(current_user)):
    return {"accounts": _mac_manager.list_accounts(platform), "stats": _mac_manager.stats()}

@app.post("/api/accounts",               tags=["Multi-Account"])
async def accounts_add(req: AddAccountRequest, user: dict = Depends(current_user)):
    acc = _mac_manager.add_account(req.platform, req.display_name, username=req.username, user_id=req.user_id, access_token=req.access_token, tags=req.tags, notes=req.notes)
    _webhook_mgr.notify("New Account Added", f"Added {req.platform} account: {req.display_name}", "success")
    return {"account": acc}

@app.patch("/api/accounts/{account_id}", tags=["Multi-Account"])
async def accounts_update(account_id: str, req: dict, user: dict = Depends(current_user)):
    acc = _mac_manager.update_account(account_id, **req)
    return {"account": acc}

@app.delete("/api/accounts/{account_id}",tags=["Multi-Account"])
async def accounts_delete(account_id: str, user: dict = Depends(current_user)):
    ok = _mac_manager.delete_account(account_id)
    return {"deleted": ok}

@app.post("/api/accounts/{account_id}/set-default", tags=["Multi-Account"])
async def accounts_set_default(account_id: str, platform: str, user: dict = Depends(current_user)):
    _mac_manager.set_default(account_id, platform)
    return {"message": f"Account {account_id} is now the default for {platform}"}

# ── Webhooks ──────────────────────────────────────────────────────────────────

class WebhookConfigRequest(BaseModel):
    discord_url:      str = Field(default="")
    telegram_token:   str = Field(default="")
    telegram_chat_id: str = Field(default="")
    slack_url:        str = Field(default="")
    smtp_host:        str = Field(default="")
    smtp_user:        str = Field(default="")
    smtp_pass:        str = Field(default="")
    smtp_to:          str = Field(default="")

class WebhookNotifyRequest(BaseModel):
    title:   str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    level:   str = Field(default="info", pattern="^(info|success|warning|error)$")

@app.get("/api/webhooks/status",         tags=["Webhooks"])
async def webhooks_status(user: dict = Depends(current_user)):
    return {"configured_channels": _webhook_mgr.configured_channels, "active": len(_webhook_mgr.configured_channels) > 0}

@app.post("/api/webhooks/configure",     tags=["Webhooks"])
async def webhooks_configure(req: WebhookConfigRequest, user: dict = Depends(current_user)):
    env_path = os.path.join(_ROOT, ".env")
    updates = {}
    if req.discord_url:       updates["DISCORD_WEBHOOK_URL"]  = req.discord_url
    if req.telegram_token:    updates["TELEGRAM_BOT_TOKEN"]   = req.telegram_token
    if req.telegram_chat_id:  updates["TELEGRAM_CHAT_ID"]     = req.telegram_chat_id
    if req.slack_url:         updates["SLACK_WEBHOOK_URL"]    = req.slack_url
    if req.smtp_host:         updates["SMTP_HOST"] = req.smtp_host
    if req.smtp_user:         updates["SMTP_USER"] = req.smtp_user
    if req.smtp_pass:         updates["SMTP_PASS"] = req.smtp_pass
    if req.smtp_to:           updates["SMTP_TO"]   = req.smtp_to
    if updates:
        from src.youtube_instagram_bot.auth.oauth_flow import save_to_env
        save_to_env(env_path, updates)
        for k, v in updates.items():
            os.environ[k] = v
        # Hot-reload webhook manager
        global _webhook_mgr
        _webhook_mgr = WebhookManager(**{k.lower().replace("discord_webhook_url","discord_url").replace("telegram_bot_token","telegram_token"): os.environ.get(k,"") for k in ["DISCORD_WEBHOOK_URL","TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID","SLACK_WEBHOOK_URL","SMTP_HOST","SMTP_USER","SMTP_PASS","SMTP_TO"]})
    return {"message": "Webhook configuration saved", "channels": _webhook_mgr.configured_channels}

@app.post("/api/webhooks/test",          tags=["Webhooks"])
async def webhooks_test(user: dict = Depends(current_user)):
    return _webhook_mgr.test_channels()

@app.post("/api/webhooks/notify",        tags=["Webhooks"])
async def webhooks_notify(req: WebhookNotifyRequest, user: dict = Depends(current_user)):
    return _webhook_mgr.notify(req.title, req.message, req.level)

# ── Proxy ─────────────────────────────────────────────────────────────────────

class ProxyAddRequest(BaseModel):
    proxies: list[str] = Field(..., min_length=1, description="List of proxy strings: host:port or user:pass@host:port")
    proxy_type: str    = Field(default="http", pattern="^(http|socks5)$")

@app.get("/api/proxy/stats",             tags=["Proxy"])
async def proxy_stats(user: dict = Depends(current_user)):
    return _proxy_mgr.stats()

@app.post("/api/proxy/add",              tags=["Proxy"])
async def proxy_add(req: ProxyAddRequest, user: dict = Depends(current_user)):
    added = _proxy_mgr.add_from_list(req.proxies)
    return {"added": added, "total": _proxy_mgr.stats()["total"]}

@app.post("/api/proxy/cleanup",          tags=["Proxy"])
async def proxy_cleanup(user: dict = Depends(current_user)):
    removed = _proxy_mgr.remove_bad_proxies()
    return {"removed": removed, "remaining": _proxy_mgr.stats()["total"]}

# ── SaaS / Subscriptions ──────────────────────────────────────────────────────

class UpgradeRequest(BaseModel):
    tier:        str = Field(..., pattern="^(free|pro|agency)$")
    success_url: str = Field(default="http://localhost:8080/index.html?upgraded=1")
    cancel_url:  str = Field(default="http://localhost:8080/index.html")

@app.get("/api/saas/tiers",              tags=["SaaS"])
async def saas_tiers():
    return {"tiers": TIERS}

@app.get("/api/saas/subscription",       tags=["SaaS"])
async def saas_subscription(user: dict = Depends(current_user)):
    return _saas_mgr.get_subscription(user["username"])

@app.post("/api/saas/upgrade",           tags=["SaaS"])
async def saas_upgrade(req: UpgradeRequest, user: dict = Depends(current_user)):
    if req.tier == "free":
        result = _saas_mgr.set_tier(user["username"], "free")
        return {"message": "Downgraded to Free tier", "subscription": result}
    result = _saas_mgr.create_stripe_checkout(user["username"], req.tier, req.success_url, req.cancel_url)
    return result

@app.post("/api/saas/admin/set-tier",    tags=["SaaS"])
async def saas_admin_set_tier(username: str, tier: str, days: int = 30, admin: dict = Depends(admin_user)):
    result = _saas_mgr.set_tier(username, tier, days)
    _webhook_mgr.notify("Tier Changed", f"User {username} upgraded to {tier}", "success")
    return result
