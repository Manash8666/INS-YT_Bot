"""
Real YouTube Data API v3 client using google-api-python-client + OAuth 2.0.

Implements:
  - OAuth2 token refresh (client_id + client_secret + refresh_token)
  - Channel info (subscribers, views, video count)
  - Video upload (resumable, supports Shorts via #Shorts tag + vertical flag)
  - Thumbnail set
  - Video like / unlike
  - Comment on video
  - Subscribe / unsubscribe to channel
  - Search videos by keyword
  - Get video details (views, likes, comments)

Quota costs are tracked per call so we never exceed the 10,000 unit/day limit.

Docs: https://developers.google.com/youtube/v3/docs
"""

import io
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

log = logging.getLogger(__name__)

OAUTH_TOKEN_URL   = "https://oauth2.googleapis.com/token"
YT_API_BASE       = "https://www.googleapis.com/youtube/v3"
YT_UPLOAD_BASE    = "https://www.googleapis.com/upload/youtube/v3"

# ── Quota costs (units per call) ──────────────────────────────────────────────
QUOTA = {
    "videos.insert":        1600,
    "videos.rate":            50,
    "videos.update":          50,
    "comments.insert":        50,
    "subscriptions.insert":   50,
    "subscriptions.delete":   50,
    "search.list":           100,
    "channels.list":           1,
    "videos.list":             1,
    "thumbnails.set":         50,
}
DAILY_QUOTA_LIMIT = 10_000


class YouTubeAPIError(Exception):
    def __init__(self, code: int, message: str, reason: str = ""):
        self.code = code
        self.message = message
        self.reason = reason
        super().__init__(f"[{code}] {message} ({reason})")


class YouTubeQuotaError(YouTubeAPIError):
    pass


class YouTubeAuthError(YouTubeAPIError):
    pass


class YouTubeDataClient:
    """
    Thin httpx wrapper for the YouTube Data API v3.

    Usage:
        client = YouTubeDataClient(client_id, client_secret, refresh_token)
        channel = client.get_channel_info()
        video_id = client.upload_video(title, description, tags, file_bytes)
    """

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 channel_id: str = ""):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.channel_id    = channel_id

        self._access_token: str = ""
        self._token_expiry: float = 0.0
        self._quota_used: int = 0
        self._quota_reset_date: str = ""
        self._http = httpx.Client(timeout=60.0)

    # ── Token management ──────────────────────────────────────────────────────

    def _ensure_token(self) -> str:
        """Return a valid access token, refreshing if expired."""
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token
        self._refresh_access_token()
        return self._access_token

    def _refresh_access_token(self) -> None:
        resp = self._http.post(OAUTH_TOKEN_URL, data={
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type":    "refresh_token",
        })
        body = resp.json()
        if "error" in body:
            raise YouTubeAuthError(401, body.get("error_description", body["error"]))
        self._access_token = body["access_token"]
        self._token_expiry = time.time() + body.get("expires_in", 3600)
        log.debug("youtube.token.refreshed")

    # ── Quota tracker ─────────────────────────────────────────────────────────

    def _charge_quota(self, operation: str) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._quota_reset_date:
            self._quota_used = 0
            self._quota_reset_date = today
        cost = QUOTA.get(operation, 1)
        if self._quota_used + cost > DAILY_QUOTA_LIMIT:
            raise YouTubeQuotaError(429,
                f"Daily quota exceeded ({self._quota_used}/{DAILY_QUOTA_LIMIT} units used)")
        self._quota_used += cost
        log.debug(f"quota charged: {operation} +{cost} → {self._quota_used}/{DAILY_QUOTA_LIMIT}")

    @property
    def quota_used(self) -> int:
        return self._quota_used

    @property
    def quota_remaining(self) -> int:
        return max(0, DAILY_QUOTA_LIMIT - self._quota_used)

    # ── Low-level helpers ─────────────────────────────────────────────────────

    def _get(self, path: str, params: dict) -> dict:
        params["key"] = ""   # not needed with OAuth but kept for compat
        headers = {"Authorization": f"Bearer {self._ensure_token()}"}
        resp = self._http.get(f"{YT_API_BASE}/{path}", params=params, headers=headers)
        return self._handle(resp)

    def _post(self, path: str, json: dict, params: dict = None) -> dict:
        headers = {"Authorization": f"Bearer {self._ensure_token()}",
                   "Content-Type": "application/json"}
        resp = self._http.post(f"{YT_API_BASE}/{path}",
                               json=json, params=params or {}, headers=headers)
        return self._handle(resp)

    def _delete(self, path: str, params: dict) -> bool:
        headers = {"Authorization": f"Bearer {self._ensure_token()}"}
        resp = self._http.delete(f"{YT_API_BASE}/{path}", params=params, headers=headers)
        if resp.status_code == 204:
            return True
        self._handle(resp)
        return True

    def _handle(self, resp: httpx.Response) -> dict:
        if resp.status_code in (401, 403):
            body = resp.json() if resp.content else {}
            errs = body.get("error", {}).get("errors", [{}])
            reason = errs[0].get("reason", "") if errs else ""
            if resp.status_code == 403 and "quotaExceeded" in reason:
                raise YouTubeQuotaError(403, "Quota exceeded", reason)
            raise YouTubeAuthError(resp.status_code,
                body.get("error", {}).get("message", "Auth error"), reason)
        if resp.status_code >= 400:
            body = resp.json() if resp.content else {}
            errs = body.get("error", {}).get("errors", [{}])
            reason = errs[0].get("reason", "") if errs else ""
            raise YouTubeAPIError(resp.status_code,
                body.get("error", {}).get("message", f"HTTP {resp.status_code}"), reason)
        return resp.json() if resp.content else {}

    # ── Channel ───────────────────────────────────────────────────────────────

    def get_channel_info(self) -> dict:
        """Return statistics for the authenticated channel."""
        self._charge_quota("channels.list")
        data = self._get("channels", {
            "part": "snippet,statistics,contentDetails",
            "mine": "true",
        })
        items = data.get("items", [])
        if not items:
            raise YouTubeAPIError(404, "Channel not found")
        item = items[0]
        stats = item.get("statistics", {})
        # Cache channel_id for later use
        if not self.channel_id:
            self.channel_id = item["id"]
        return {
            "channel_id":        item["id"],
            "title":             item["snippet"]["title"],
            "description":       item["snippet"].get("description", ""),
            "subscriber_count":  int(stats.get("subscriberCount", 0)),
            "view_count":        int(stats.get("viewCount", 0)),
            "video_count":       int(stats.get("videoCount", 0)),
            "hidden_subscriber": stats.get("hiddenSubscriberCount", False),
        }

    # ── Video upload ──────────────────────────────────────────────────────────

    def upload_video(
        self,
        title: str,
        description: str,
        tags: list[str],
        file_bytes: bytes,
        is_short: bool = False,
        privacy: str = "public",
        category_id: str = "22",    # 22 = People & Blogs
        thumbnail_bytes: Optional[bytes] = None,
    ) -> str:
        """
        Upload a video using the resumable upload protocol.
        Returns the YouTube video ID.

        Shorts: set is_short=True — appends #Shorts to title/description
        and uses vertical aspect ratio hint (categoryId=22).
        """
        self._charge_quota("videos.insert")

        # Prepare metadata
        if is_short:
            if "#Shorts" not in title:
                title = title + " #Shorts"
            if "#Shorts" not in description:
                description = description + "\n\n#Shorts"
            tags = list(set(tags + ["Shorts", "YouTubeShorts"]))

        metadata = {
            "snippet": {
                "title":       title[:100],
                "description": description[:5000],
                "tags":        tags[:500],
                "categoryId":  category_id,
            },
            "status": {
                "privacyStatus":          privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        # Step 1: initiate resumable upload session
        headers = {
            "Authorization":           f"Bearer {self._ensure_token()}",
            "Content-Type":            "application/json",
            "X-Upload-Content-Type":   "video/*",
            "X-Upload-Content-Length": str(len(file_bytes)),
        }
        init_resp = self._http.post(
            f"{YT_UPLOAD_BASE}/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=metadata,
            headers=headers,
        )
        if init_resp.status_code not in (200, 201):
            self._handle(init_resp)
        upload_url = init_resp.headers.get("Location")
        if not upload_url:
            raise YouTubeAPIError(500, "No resumable upload URL returned")

        # Step 2: upload the bytes
        upload_headers = {
            "Authorization":  f"Bearer {self._ensure_token()}",
            "Content-Type":   "video/*",
            "Content-Length": str(len(file_bytes)),
        }
        upload_resp = self._http.put(upload_url, content=file_bytes, headers=upload_headers)
        body = self._handle(upload_resp)
        video_id = body.get("id")
        if not video_id:
            raise YouTubeAPIError(500, "Upload succeeded but no video ID returned")

        log.info(f"youtube.upload.complete video_id={video_id} short={is_short}")

        # Step 3: set thumbnail if provided
        if thumbnail_bytes:
            try:
                self.set_thumbnail(video_id, thumbnail_bytes)
            except Exception as exc:
                log.warning(f"youtube.thumbnail.failed video_id={video_id} err={exc}")

        return video_id

    # ── Thumbnail ─────────────────────────────────────────────────────────────

    def set_thumbnail(self, video_id: str, image_bytes: bytes) -> None:
        """Set a custom thumbnail for a video."""
        self._charge_quota("thumbnails.set")
        headers = {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type":  "image/jpeg",
        }
        resp = self._http.post(
            f"{YT_UPLOAD_BASE}/thumbnails/set",
            params={"videoId": video_id, "uploadType": "media"},
            content=image_bytes,
            headers=headers,
        )
        self._handle(resp)

    # ── Like / unlike ─────────────────────────────────────────────────────────

    def like_video(self, video_id: str) -> bool:
        """Like a video (rate = 'like'). Returns True on success."""
        self._charge_quota("videos.rate")
        self._post("videos/rate", {}, params={"id": video_id, "rating": "like"})
        return True

    def unlike_video(self, video_id: str) -> bool:
        """Remove a like from a video."""
        self._charge_quota("videos.rate")
        self._post("videos/rate", {}, params={"id": video_id, "rating": "none"})
        return True

    # ── Comment ───────────────────────────────────────────────────────────────

    def comment_on_video(self, video_id: str, text: str) -> str:
        """Post a top-level comment. Returns the comment ID."""
        self._charge_quota("comments.insert")
        data = self._post("commentThreads", {
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {"textOriginal": text[:10000]}
                },
            },
        }, params={"part": "snippet"})
        return data.get("id", "")

    # ── Subscribe / unsubscribe ───────────────────────────────────────────────

    def subscribe_to_channel(self, channel_id: str) -> str:
        """Subscribe to a channel. Returns subscription ID."""
        self._charge_quota("subscriptions.insert")
        data = self._post("subscriptions", {
            "snippet": {
                "resourceId": {
                    "kind":      "youtube#channel",
                    "channelId": channel_id,
                }
            },
        }, params={"part": "snippet"})
        return data.get("id", "")

    def unsubscribe_from_channel(self, subscription_id: str) -> bool:
        """Unsubscribe using a subscription ID."""
        self._charge_quota("subscriptions.delete")
        return self._delete("subscriptions", params={"id": subscription_id})

    # ── Search & video details ────────────────────────────────────────────────

    def search_videos(self, query: str, max_results: int = 25) -> list[dict]:
        """Search YouTube. Returns list of video metadata dicts."""
        self._charge_quota("search.list")
        data = self._get("search", {
            "part":       "snippet",
            "q":          query,
            "type":       "video",
            "maxResults": min(max_results, 50),
            "order":      "relevance",
        })
        results = []
        for item in data.get("items", []):
            vid_id = item.get("id", {}).get("videoId")
            snip   = item.get("snippet", {})
            if vid_id:
                results.append({
                    "video_id":    vid_id,
                    "title":       snip.get("title"),
                    "channel_id":  snip.get("channelId"),
                    "channel":     snip.get("channelTitle"),
                    "published_at":snip.get("publishedAt"),
                })
        return results

    def get_video_stats(self, video_id: str) -> dict:
        """Return statistics for a single video."""
        self._charge_quota("videos.list")
        data = self._get("videos", {
            "part": "snippet,statistics,status",
            "id":   video_id,
        })
        items = data.get("items", [])
        if not items:
            raise YouTubeAPIError(404, f"Video {video_id} not found")
        item  = items[0]
        stats = item.get("statistics", {})
        return {
            "video_id":      item["id"],
            "title":         item["snippet"]["title"],
            "view_count":    int(stats.get("viewCount", 0)),
            "like_count":    int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
            "privacy":       item["status"]["privacyStatus"],
        }

    def close(self) -> None:
        self._http.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
