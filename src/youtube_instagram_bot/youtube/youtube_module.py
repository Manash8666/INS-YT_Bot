"""
Real YouTube_Module — YouTube Data API v3 backed.

Wraps YouTubeDataClient with:
  - Daily counters (upload, like, comment, subscribe) matching quota costs
  - Randomised human delays between actions
  - Simulation mode when no credentials are configured
  - Retry on transient errors via Retry_Handler
"""

import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Optional

from ..models.core import Platform, LogLevel
from ..storage.storage import Storage
from ..logger import Logger

log = logging.getLogger(__name__)

# ── Safety thresholds ─────────────────────────────────────────────────────────
UPLOADS_PER_DAY    = 6     # 1,600 quota units each → ~9,600 of 10,000
LIKES_PER_DAY      = 50
COMMENTS_PER_DAY   = 20
SUBSCRIBES_PER_DAY = 30
MIN_DELAY          = 30.0  # seconds between actions
MAX_DELAY          = 90.0


class DailyCounter:
    def __init__(self, limit: int):
        self.limit = limit
        self._count = 0
        self._reset_date = datetime.now(timezone.utc).date()

    def _maybe_reset(self):
        today = datetime.now(timezone.utc).date()
        if today != self._reset_date:
            self._count = 0
            self._reset_date = today

    def increment(self) -> bool:
        self._maybe_reset()
        if self._count >= self.limit:
            return False
        self._count += 1
        return True

    @property
    def remaining(self) -> int:
        self._maybe_reset()
        return max(0, self.limit - self._count)

    @property
    def count(self) -> int:
        self._maybe_reset()
        return self._count


class YouTube_Module:
    """
    Real YouTube module.

    Pass yt_client=YouTubeDataClient(...) to activate live mode.
    Without it, every method returns a simulation result.
    """

    def __init__(
        self,
        auth,
        retry,
        rate_limiter,
        storage: Storage,
        logger: Logger,
        yt_client=None,            # YouTubeDataClient | None
    ):
        self.auth         = auth
        self.retry        = retry
        self.rate_limiter = rate_limiter
        self.storage      = storage
        self.logger       = logger
        self.yt_client    = yt_client

        self._uploads_today    = DailyCounter(UPLOADS_PER_DAY)
        self._likes_today      = DailyCounter(LIKES_PER_DAY)
        self._comments_today   = DailyCounter(COMMENTS_PER_DAY)
        self._subscribes_today = DailyCounter(SUBSCRIBES_PER_DAY)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def _live(self) -> bool:
        return self.yt_client is not None

    def _human_delay(self):
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    def _log(self, msg: str, level: str = "info"):
        getattr(log, level)(msg)
        self.logger.log_action(account_id="youtube", job_id=None, outcome=msg)

    # ── Upload video / Short ──────────────────────────────────────────────────

    def upload_video(
        self,
        account_id: str,
        content_id: str,
        vertical: bool = False,
        thumbnail_id: Optional[str] = None,
        title: str = "New Video",
        description: str = "",
        tags: Optional[list] = None,
        privacy: str = "public",
    ) -> str:
        """Upload a video or Short to YouTube. Returns platform video ID."""
        if not self._uploads_today.increment():
            raise Exception(f"Daily upload cap ({UPLOADS_PER_DAY}) reached")

        if not self._live:
            self._log(f"[SIM] upload_video content={content_id} short={vertical}")
            import time as _t
            return f"yt_sim_{content_id[:8]}_{int(_t.time())}"

        # Fetch the video bytes from storage
        try:
            file_bytes = self.storage.read_content(content_id)
        except Exception as exc:
            raise Exception(f"Content {content_id} not found in storage: {exc}")

        # Fetch thumbnail bytes if provided
        thumb_bytes = None
        if thumbnail_id:
            try:
                thumb_bytes = self.storage.read_content(thumbnail_id)
            except Exception:
                pass

        # Rate limit
        self.rate_limiter.acquire(Platform.YOUTUBE, account_id)

        # Upload via API
        video_id = self.yt_client.upload_video(
            title=title,
            description=description,
            tags=tags or [],
            file_bytes=file_bytes,
            is_short=vertical,
            privacy=privacy,
            thumbnail_bytes=thumb_bytes,
        )

        self._log(f"Uploaded video {video_id} (short={vertical})")
        return video_id

    def attach_thumbnail(self, post_id: str, account_id: str, thumbnail_id: str) -> None:
        """Attach a thumbnail to an existing YouTube video."""
        if not self._live:
            self._log(f"[SIM] attach_thumbnail post={post_id}")
            return
        try:
            thumb_bytes = self.storage.read_content(thumbnail_id)
            self.yt_client.set_thumbnail(post_id, thumb_bytes)
            self._log(f"Thumbnail set for video {post_id}")
        except Exception as exc:
            self._log(f"Thumbnail failed for {post_id}: {exc}", "warning")

    # ── Like / unlike ─────────────────────────────────────────────────────────

    def like_video(self, video_id: str) -> dict:
        """Like a YouTube video."""
        result = {
            "mode":     "live" if self._live else "simulation",
            "video_id": video_id,
            "liked":    0,
            "skipped_daily_cap": 0,
            "errors":   [],
        }
        if not self._likes_today.increment():
            result["skipped_daily_cap"] = 1
            result["errors"].append(f"Daily like cap ({LIKES_PER_DAY}) reached")
            return result

        if not self._live:
            result["liked"] = 1
            result["message"] = "Simulation — configure YouTube credentials in Settings"
            return result

        try:
            self.rate_limiter.acquire(Platform.YOUTUBE, "like")
            self.yt_client.like_video(video_id)
            result["liked"] = 1
            self._log(f"Liked video {video_id}")
        except Exception as exc:
            self._likes_today._count -= 1   # refund
            result["errors"].append(str(exc))

        return result

    # ── Comment ───────────────────────────────────────────────────────────────

    def comment_on_video(self, video_id: str, text: str) -> dict:
        """Post a comment on a YouTube video."""
        result = {
            "mode":        "live" if self._live else "simulation",
            "video_id":    video_id,
            "commented":   0,
            "comment_id":  None,
            "skipped_daily_cap": 0,
            "errors": [],
        }
        if not self._comments_today.increment():
            result["skipped_daily_cap"] = 1
            result["errors"].append(f"Daily comment cap ({COMMENTS_PER_DAY}) reached")
            return result

        if not self._live:
            result["commented"] = 1
            result["comment_id"] = "sim_comment_id"
            result["message"] = "Simulation — configure YouTube credentials in Settings"
            return result

        try:
            self.rate_limiter.acquire(Platform.YOUTUBE, "comment")
            comment_id = self.yt_client.comment_on_video(video_id, text)
            result["commented"]  = 1
            result["comment_id"] = comment_id
            self._log(f"Commented on video {video_id}")
        except Exception as exc:
            self._comments_today._count -= 1
            result["errors"].append(str(exc))

        return result

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def subscribe_to_channel(self, channel_id: str) -> dict:
        """Subscribe to a YouTube channel."""
        result = {
            "mode":            "live" if self._live else "simulation",
            "channel_id":      channel_id,
            "subscribed":      0,
            "subscription_id": None,
            "skipped_daily_cap": 0,
            "errors": [],
        }
        if not self._subscribes_today.increment():
            result["skipped_daily_cap"] = 1
            result["errors"].append(f"Daily subscribe cap ({SUBSCRIBES_PER_DAY}) reached")
            return result

        if not self._live:
            result["subscribed"] = 1
            result["subscription_id"] = "sim_sub_id"
            result["message"] = "Simulation — configure YouTube credentials in Settings"
            return result

        try:
            self.rate_limiter.acquire(Platform.YOUTUBE, "subscribe")
            sub_id = self.yt_client.subscribe_to_channel(channel_id)
            result["subscribed"]      = 1
            result["subscription_id"] = sub_id
            self._log(f"Subscribed to channel {channel_id}")
        except Exception as exc:
            self._subscribes_today._count -= 1
            result["errors"].append(str(exc))

        return result

    # ── Search & engage ───────────────────────────────────────────────────────

    def search_and_engage(
        self,
        query: str,
        max_videos: int = 10,
        do_like: bool = True,
        do_comment: bool = False,
        do_subscribe: bool = False,
        comment_text: str = "Great video! 🔥",
    ) -> dict:
        """
        Search for videos by keyword then like/comment/subscribe on them.
        This is the YouTube equivalent of follow_by_tag.
        """
        result = {
            "mode":        "live" if self._live else "simulation",
            "query":       query,
            "videos_found": 0,
            "liked":       0,
            "commented":   0,
            "subscribed":  0,
            "skipped_quota": 0,
            "errors":      [],
        }

        if not self._live:
            # Simulate
            for _ in range(min(max_videos, 10)):
                if do_like and self._likes_today.increment():
                    result["liked"] += 1
                if do_comment and self._comments_today.increment():
                    result["commented"] += 1
                if do_subscribe and self._subscribes_today.increment():
                    result["subscribed"] += 1
            result["videos_found"] = result["liked"] or result["commented"] or result["subscribed"]
            result["message"] = "Simulation — configure YouTube credentials in Settings"
            return result

        try:
            videos = self.yt_client.search_videos(query, max_results=min(max_videos, 25))
            result["videos_found"] = len(videos)
            seen_channels: set[str] = set()

            for video in videos:
                video_id  = video["video_id"]
                channel_id = video.get("channel_id", "")

                # Like
                if do_like:
                    if not self._likes_today.increment():
                        result["skipped_quota"] += 1
                    else:
                        try:
                            self.rate_limiter.acquire(Platform.YOUTUBE, f"like_{video_id}")
                            self.yt_client.like_video(video_id)
                            result["liked"] += 1
                            self._human_delay()
                        except Exception as exc:
                            self._likes_today._count -= 1
                            result["errors"].append(f"like {video_id}: {exc}")

                # Comment
                if do_comment:
                    if not self._comments_today.increment():
                        result["skipped_quota"] += 1
                    else:
                        try:
                            self.rate_limiter.acquire(Platform.YOUTUBE, f"comment_{video_id}")
                            self.yt_client.comment_on_video(video_id, comment_text)
                            result["commented"] += 1
                            self._human_delay()
                        except Exception as exc:
                            self._comments_today._count -= 1
                            result["errors"].append(f"comment {video_id}: {exc}")

                # Subscribe (once per channel)
                if do_subscribe and channel_id and channel_id not in seen_channels:
                    seen_channels.add(channel_id)
                    if not self._subscribes_today.increment():
                        result["skipped_quota"] += 1
                    else:
                        try:
                            self.rate_limiter.acquire(Platform.YOUTUBE, f"sub_{channel_id}")
                            self.yt_client.subscribe_to_channel(channel_id)
                            result["subscribed"] += 1
                            self._human_delay()
                        except Exception as exc:
                            self._subscribes_today._count -= 1
                            result["errors"].append(f"subscribe {channel_id}: {exc}")

        except Exception as exc:
            result["errors"].append(str(exc))
            self._log(f"search_and_engage failed: {exc}", "error")

        return result

    # ── Channel info ──────────────────────────────────────────────────────────

    def get_channel_info(self) -> dict:
        """Return channel stats for the authenticated account."""
        if not self._live:
            return {
                "mode": "simulation",
                "channel_id": "UC_sim",
                "title": "Your Channel (simulated)",
                "subscriber_count": 0,
                "view_count": 0,
                "video_count": 0,
            }
        try:
            info = self.yt_client.get_channel_info()
            info["mode"] = "live"
            return info
        except Exception as exc:
            return {"mode": "live", "error": str(exc)}

    def get_video_stats(self, video_id: str) -> dict:
        """Return stats for a specific video."""
        if not self._live:
            return {"mode": "simulation", "video_id": video_id, "view_count": 0}
        try:
            stats = self.yt_client.get_video_stats(video_id)
            stats["mode"] = "live"
            # Ensure channel_id is present for magic workflow
            if "channel_id" not in stats:
                stats["channel_id"] = ""
            return stats
        except Exception as exc:
            return {"mode": "live", "error": str(exc)}

    # ── Stats ─────────────────────────────────────────────────────────────────

    def daily_stats(self) -> dict:
        return {
            "mode":               "live" if self._live else "simulation",
            "youtube_configured": self._live,
            "quota_used":         self.yt_client.quota_used if self._live else 0,
            "quota_remaining":    self.yt_client.quota_remaining if self._live else 10000,
            "uploads_today":      self._uploads_today.count,
            "uploads_remaining":  self._uploads_today.remaining,
            "likes_today":        self._likes_today.count,
            "likes_remaining":    self._likes_today.remaining,
            "comments_today":     self._comments_today.count,
            "subscribes_today":   self._subscribes_today.count,
            "daily_caps": {
                "upload":    UPLOADS_PER_DAY,
                "like":      LIKES_PER_DAY,
                "comment":   COMMENTS_PER_DAY,
                "subscribe": SUBSCRIBES_PER_DAY,
            },
        }



    # ════════════════════════════════════════════════════════════════════════
    #  WATCH TIME + REAL-ACCOUNT SUBSCRIBER GROWTH
    # ════════════════════════════════════════════════════════════════════════

    def get_watch_engine(self):
        """Return (or lazily create) the WatchTimeEngine for this module."""
        if not hasattr(self, "_watch_engine") or self._watch_engine is None:
            from .watch_time_engine import YouTubeWatchTimeEngine
            self._watch_engine = YouTubeWatchTimeEngine(self, self.logger)
        return self._watch_engine

    def accumulate_watch_time(
        self,
        target_channel_id: str,
        sessions: int = 50,
    ) -> dict:
        """
        Accumulate watch time toward the YouTube Partner Program 4,000-hour goal.

        Each session watches 60-85% of a video (mimics real viewer behaviour).
        Only real accounts (non-bot channels) are counted.

        Returns full monetization progress report.
        """
        return self.get_watch_engine().accumulate_watch_time(
            target_channel_id=target_channel_id,
            sessions=sessions,
        )

    def grow_real_subscribers(
        self,
        query: str,
        max_subs: int = 20,
        min_channel_subs: int = 10,
        min_channel_videos: int = 1,
    ) -> dict:
        """
        Find and subscribe to REAL channels only (bot-filtered).

        Real-account checks:
          - Has at least min_channel_videos uploaded videos
          - Has at least min_channel_subs subscribers
          - Title does not contain bot-like strings
        Subscribing to real, active channels triggers reciprocal subscriptions.
        """
        return self.get_watch_engine().grow_subscribers_real_only(
            query=query,
            max_subs=max_subs,
            min_channel_subs=min_channel_subs,
            min_channel_videos=min_channel_videos,
        )

    def monetization_report(self) -> dict:
        """
        Full YouTube Partner Program eligibility report.

        Shows:
          - Watch hours accumulated this session
          - % progress toward 4,000-hour threshold
          - Subscriber progress toward 1,000-subscriber threshold
          - Personalised recommendation
        """
        return self.get_watch_engine().monetization_report()

    def engage_with_subscribers(
        self,
        comment_text: str = "Great content! Keep it up 🔥",
        max_engage: int = 10,
        do_like: bool = True,
        do_comment: bool = False,
    ) -> dict:
        """Like/comment on niche channel videos — builds reciprocal engagement and watch time."""
        return self.get_watch_engine().engage_with_subscribers(
            comment_text=comment_text,
            max_engage=max_engage,
            do_like=do_like,
            do_comment=do_comment,
        )


    def engage_with_subscribers(
        self,
        comment_text: str = "Great content! Keep it up 🔥",
        max_engage: int = 10,
        do_like: bool = True,
        do_comment: bool = False,
    ) -> dict:
        """
        Like/comment on niche channel videos — builds reciprocal engagement and watch time.
        OPTIONAL action — triggered separately by the user.
        """
        return self.get_watch_engine().engage_with_subscribers(
            comment_text=comment_text,
            max_engage=max_engage,
            do_like=do_like,
            do_comment=do_comment,
        )
