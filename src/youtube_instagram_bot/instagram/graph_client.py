"""
Real Instagram Graph API client.

Implements:
  - Hashtag search  → get recent media → extract owner user IDs
  - Follow user     → POST /{ig-user-id}/following
  - Unfollow user   → DELETE /{ig-user-id}/following/{target-id}
  - Like media      → POST /{media-id}/likes
  - Unlike media    → DELETE /{media-id}/likes
  - Get followers   → GET /{ig-user-id}/followers
  - Get followings  → GET /{ig-user-id}/followings

All calls go through the official Facebook Graph API v19.0.
Docs: https://developers.facebook.com/docs/instagram-api
"""

import random
import time
import logging
from typing import Optional
from datetime import datetime, timedelta

import httpx

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v19.0"


class InstagramAPIError(Exception):
    """Raised when the Graph API returns an error response."""
    def __init__(self, code: int, message: str, fb_error: Optional[dict] = None):
        self.code = code
        self.message = message
        self.fb_error = fb_error or {}
        super().__init__(f"[{code}] {message}")


class InstagramRateLimitError(InstagramAPIError):
    """HTTP 429 or error code 32/613 from Instagram."""
    pass


class InstagramAuthError(InstagramAPIError):
    """Token expired / revoked (error code 190)."""
    pass


class InstagramGraphClient:
    """
    Thin httpx wrapper for the Instagram Graph API.

    Every method raises:
        InstagramRateLimitError  – back off and retry
        InstagramAuthError       – token needs refresh / re-auth
        InstagramAPIError        – other Graph errors
    """

    def __init__(self, access_token: str, ig_user_id: str, timeout: float = 30.0):
        self.access_token = access_token
        self.ig_user_id = ig_user_id
        self._client = httpx.Client(timeout=timeout)

    # ── Low-level helpers ────────────────────────────────────────────────────

    def _get(self, path: str, params: dict = None) -> dict:
        p = {"access_token": self.access_token, **(params or {})}
        resp = self._client.get(f"{GRAPH_BASE}/{path}", params=p)
        return self._handle(resp)

    def _post(self, path: str, data: dict = None) -> dict:
        d = {"access_token": self.access_token, **(data or {})}
        resp = self._client.post(f"{GRAPH_BASE}/{path}", data=d)
        return self._handle(resp)

    def _delete(self, path: str, params: dict = None) -> dict:
        p = {"access_token": self.access_token, **(params or {})}
        resp = self._client.delete(f"{GRAPH_BASE}/{path}", params=p)
        return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> dict:
        if resp.status_code == 429:
            raise InstagramRateLimitError(429, "Rate limit exceeded (HTTP 429)")
        body = resp.json() if resp.content else {}
        if "error" in body:
            err = body["error"]
            code = err.get("code", 0)
            msg  = err.get("message", "Unknown error")
            if code in (190, 102, 467):
                raise InstagramAuthError(code, msg, err)
            if code in (32, 613, 17, 4):
                raise InstagramRateLimitError(code, msg, err)
            raise InstagramAPIError(code, msg, err)
        resp.raise_for_status()
        return body

    # ── Hashtag search ───────────────────────────────────────────────────────

    def search_hashtag_id(self, tag: str) -> Optional[str]:
        """Return the IG hashtag object ID for a tag name (without #)."""
        tag = tag.lstrip("#")
        data = self._get("ig_hashtag_search", {
            "user_id": self.ig_user_id,
            "q": tag,
        })
        items = data.get("data", [])
        return items[0]["id"] if items else None

    def get_recent_media_by_hashtag(self, hashtag_id: str, limit: int = 50) -> list[dict]:
        """Return recent public media objects for a hashtag."""
        data = self._get(f"{hashtag_id}/recent_media", {
            "user_id": self.ig_user_id,
            "fields": "id,owner,username,timestamp",
            "limit": min(limit, 50),
        })
        return data.get("data", [])

    def get_top_media_by_hashtag(self, hashtag_id: str, limit: int = 50) -> list[dict]:
        """Return top media objects for a hashtag."""
        data = self._get(f"{hashtag_id}/top_media", {
            "user_id": self.ig_user_id,
            "fields": "id,owner,username,timestamp",
            "limit": min(limit, 50),
        })
        return data.get("data", [])

    # ── User info ────────────────────────────────────────────────────────────

    def get_user_info(self, user_id: str) -> dict:
        """Return basic profile info for a user."""
        return self._get(user_id, {"fields": "id,name,biography,followers_count,follows_count,media_count"})

    def get_own_followers(self, limit: int = 100) -> list[dict]:
        """Return a list of your own followers."""
        data = self._get(f"{self.ig_user_id}/followers", {
            "fields": "id,username",
            "limit": min(limit, 200),
        })
        return data.get("data", [])

    def get_own_followings(self, limit: int = 100) -> list[dict]:
        """Return a list of users you follow."""
        data = self._get(f"{self.ig_user_id}/following", {
            "fields": "id,username",
            "limit": min(limit, 200),
        })
        return data.get("data", [])

    # ── Follow / unfollow ────────────────────────────────────────────────────

    def follow_user(self, target_user_id: str) -> bool:
        """Follow a user. Returns True on success."""
        result = self._post(f"{self.ig_user_id}/following", {"user_id": target_user_id})
        return bool(result.get("success", False))

    def unfollow_user(self, target_user_id: str) -> bool:
        """Unfollow a user. Returns True on success."""
        result = self._delete(f"{self.ig_user_id}/following/{target_user_id}")
        return bool(result.get("success", False))

    # ── Like / unlike ────────────────────────────────────────────────────────

    def like_media(self, media_id: str) -> bool:
        """Like a media object. Returns True on success."""
        result = self._post(f"{self.ig_user_id}/likes", {"media_id": media_id})
        return bool(result.get("success", False))

    def unlike_media(self, media_id: str) -> bool:
        """Unlike a media object. Returns True on success."""
        result = self._delete(f"{self.ig_user_id}/likes/{media_id}")
        return bool(result.get("success", False))

    def get_user_recent_media(self, user_id: str, limit: int = 5) -> list[dict]:
        """Get recent media posted by a user to check daily activity."""
        data = self._get(f"{user_id}/media", {
            "fields": "id,timestamp,media_type,like_count,comments_count",
            "limit": min(limit, 10),
        })
        return data.get("data", [])

    def get_user_profile(self, user_id: str) -> dict:
        """Get user profile to verify account is real and active."""
        return self._get(user_id, {
            "fields": "id,username,biography,followers_count,follows_count,media_count,is_verified"
        })

    def comment_on_media(self, media_id: str, text: str) -> dict:
        """Post a comment on a media object."""
        return self._post(f"{media_id}/comments", {"message": text})

    def get_user_recent_media(self, user_id: str, limit: int = 5) -> list[dict]:
        """Get recent media posted by a user — used to check daily activity."""
        data = self._get(f"{user_id}/media", {
            "fields": "id,timestamp,media_type,like_count,comments_count",
            "limit": min(limit, 10),
        })
        return data.get("data", [])

    def get_user_profile(self, user_id: str) -> dict:
        """Get user profile to verify account is real and active."""
        return self._get(user_id, {
            "fields": "id,username,biography,followers_count,follows_count,media_count,is_verified"
        })

    def comment_on_media(self, media_id: str, text: str) -> dict:
        """Post a comment on a media object owned by us."""
        return self._post(f"{media_id}/comments", {"message": text})
    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

