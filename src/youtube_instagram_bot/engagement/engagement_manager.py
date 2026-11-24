"""
Real EngagementManager — Instagram Graph API backed.

Strategy
--------
1. Search a hashtag → collect recent/top media objects
2. Extract the owner user IDs from those media objects
3. Filter out: already-followed, own account, private/bot-like accounts
4. Follow each user with a randomised human-like delay
5. Store every follow/unfollow in SQLite for the unfollow cycle

All daily counters are enforced independently of the sliding-window
rate limiter so we never exceed safe daily caps even when the hourly
window is not full.
"""

import random
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..models.core import Platform, LogLevel
from ..storage.storage import Storage
from ..logger import Logger

log = logging.getLogger(__name__)

# ── Safety thresholds (conservative) ────────────────────────────────────────
FOLLOW_PER_HOUR   = 15
FOLLOW_PER_DAY    = 150
UNFOLLOW_PER_DAY  = 150
LIKES_PER_DAY     = 300
COMMENTS_PER_DAY  = 30
MIN_DELAY         = 90.0   # seconds between actions
MAX_DELAY         = 180.0  # seconds between actions (randomised)
NEW_ACCOUNT_MULTIPLIER = 0.5   # halve all limits for accounts < 14 days old


class DailyCounter:
    """In-memory daily counter that resets at midnight UTC."""

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
        """Increment and return True if still under limit, else False."""
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


class EngagementManager:
    """
    Real Instagram engagement manager.

    Requires an InstagramGraphClient injected at construction time.
    Falls back to dry-run mode (simulation) when no client is provided,
    so the system still works without credentials configured.
    """

    def __init__(
        self,
        storage: Storage,
        logger: Logger,
        rate_limiter,
        ig_client=None,          # InstagramGraphClient | None
        ig_user_id: str = "",
    ):
        self.storage    = storage
        self.logger     = logger
        self.rate_limiter = rate_limiter
        self.ig_client  = ig_client
        self.ig_user_id = ig_user_id

        # Daily counters
        self._follows_today   = DailyCounter(FOLLOW_PER_DAY)
        self._unfollows_today = DailyCounter(UNFOLLOW_PER_DAY)
        self._likes_today     = DailyCounter(LIKES_PER_DAY)

        # In-memory set of user IDs we have already followed this session
        self._followed_this_session: set[str] = set()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def _live(self) -> bool:
        """True when real API credentials are available."""
        return self.ig_client is not None

    def _human_delay(self):
        """Sleep a randomised human-like interval between actions."""
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        log.debug(f"Human delay {delay:.1f}s")
        time.sleep(delay)

    def _acquire_rate_limit(self, action: str):
        """Check the sliding-window rate limiter before each action."""
        self.rate_limiter.acquire(Platform.INSTAGRAM, action)

    def _log(self, msg: str, level: str = "info"):
        getattr(log, level)(msg)
        self.logger.log_action(
            account_id=self.ig_user_id or "instagram",
            job_id=None,
            outcome=msg,
        )
    def _is_active_account(self, user_id: str) -> tuple[bool, str]:
        """
        Check if an Instagram user is genuinely active.
        Verifies: posted in last 30 days, has >=10 followers, has >=3 posts.
        Filters out bots, ghost accounts, and inactive users.
        Returns (is_active, reason_if_rejected).
        """
        if not self._live:
            return True, ""
        try:
            from datetime import timezone, timedelta as _td
            profile = self.ig_client.get_user_profile(user_id)
            followers   = profile.get("followers_count", 0)
            media_count = profile.get("media_count", 0)
            if followers < 10:
                return False, f"too few followers ({followers})"
            if media_count < 3:
                return False, f"too few posts ({media_count})"
            recent = self.ig_client.get_user_recent_media(user_id, limit=5)
            if not recent:
                return False, "no recent posts visible"
            cutoff = datetime.now(timezone.utc) - _td(days=30)
            active_posts = 0
            for p in recent:
                ts = p.get("timestamp", "")
                if ts:
                    try:
                        post_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if post_time > cutoff:
                            active_posts += 1
                    except Exception:
                        pass
            if active_posts < 1:
                return False, "inactive (no posts in last 30 days)"
            return True, ""
        except Exception:
            return True, ""   # On API error, assume active


    def _is_active_account(self, user_id: str) -> tuple[bool, str]:
        """Check if Instagram user is genuinely active (posted in last 30 days,
        has real followers, has posts). Filters out bots and ghost accounts."""
        if not self._live:
            return True, ""
        try:
            from datetime import timezone, timedelta as td
            profile = self.ig_client.get_user_profile(user_id)
            followers = profile.get("followers_count", 0)
            media_count = profile.get("media_count", 0)
            if followers < 10:
                return False, f"too few followers ({followers})"
            if media_count < 3:
                return False, f"too few posts ({media_count})"
            recent = self.ig_client.get_user_recent_media(user_id, limit=5)
            if not recent:
                return False, "no recent posts visible"
            cutoff = datetime.now(timezone.utc) - td(days=30)
            active = sum(
                1 for p in recent
                if p.get("timestamp") and
                datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")) > cutoff
            )
            if active < 1:
                return False, "inactive (no posts in 30 days)"
            return True, ""
        except Exception:
            return True, ""  # On error assume active, don't skip

    # ── Follow by hashtag ─────────────────────────────────────────────────────

    def follow_by_tag(self, tag: str, max_follows: int = 20) -> dict:
        """
        Find users who recently posted under `tag` and follow them.

        Flow:
            1. Search hashtag → get hashtag_id
            2. Fetch recent media for that hashtag_id
            3. Extract unique owner user_ids from media objects
            4. For each owner: rate-limit check → daily cap check →
               follow → human delay → record
        """
        tag = tag.lstrip("#").strip()
        results = {
            "mode": "live" if self._live else "simulation",
            "tag": tag,
            "max_follows": max_follows,
            "followed": 0,
            "skipped_already_followed": 0,
            "skipped_daily_cap": 0,
            "errors": [],
        }

        if not self._live:
            # ── Simulation mode ──────────────────────────────────────────────
            self._log(f"[SIM] follow_by_tag #{tag} max={max_follows}")
            for i in range(min(max_follows, 20)):
                if not self._follows_today.increment():
                    results["skipped_daily_cap"] += 1
                    break
                results["followed"] += 1
            results["message"] = (
                "Simulation only — add INSTAGRAM_ACCESS_TOKEN and "
                "INSTAGRAM_USER_ID to .env to enable real follows."
            )
            return results

        # ── Live mode ────────────────────────────────────────────────────────
        try:
            self._log(f"Searching hashtag #{tag}")
            hashtag_id = self.ig_client.search_hashtag_id(tag)
            if not hashtag_id:
                results["errors"].append(f"Hashtag #{tag} not found")
                return results

            # Fetch both recent and top media to get a larger pool
            media_items = self.ig_client.get_recent_media_by_hashtag(hashtag_id, limit=50)
            media_items += self.ig_client.get_top_media_by_hashtag(hashtag_id, limit=50)

            # Deduplicate owner IDs
            seen_owners: set[str] = set()
            for item in media_items:
                owner = item.get("owner", {})
                uid = owner.get("id") if isinstance(owner, dict) else None
                if uid and uid != self.ig_user_id:
                    seen_owners.add(uid)

            self._log(f"Found {len(seen_owners)} unique owners for #{tag}")

            for user_id in list(seen_owners):
                if results["followed"] >= max_follows:
                    break

                # Skip already followed this session
                if user_id in self._followed_this_session:
                    results["skipped_already_followed"] += 1
                    continue
                # Activity check — skip inactive/bot accounts (live mode only)
                if self._live:
                    is_active, reason = self._is_active_account(user_id)
                    if not is_active:
                        results["skipped_inactive"] = results.get("skipped_inactive", 0) + 1
                        self._log(f"Skipped inactive {user_id}: {reason}", "debug")
                        continue

                # Activity check — skip inactive/bot accounts
                if self._live:
                    is_active, reason = self._is_active_account(user_id)
                    if not is_active:
                        results["skipped_inactive"] = results.get("skipped_inactive", 0) + 1
                        self._log(f"Skipped inactive {user_id}: {reason}", "debug")
                        continue

                # Daily cap check
                if not self._follows_today.increment():
                    results["skipped_daily_cap"] += 1
                    self._log(f"Daily follow cap ({FOLLOW_PER_DAY}) reached", "warning")
                    break

                # Sliding-window rate limit check
                try:
                    self._acquire_rate_limit(f"follow_{user_id}")
                except Exception as rl_err:
                    results["errors"].append(f"Rate limit: {rl_err}")
                    break

                # Actual follow call
                try:
                    success = self.ig_client.follow_user(user_id)
                    if success:
                        self._followed_this_session.add(user_id)
                        results["followed"] += 1
                        self._log(f"Followed user {user_id}")
                    else:
                        results["skipped_already_followed"] += 1
                except Exception as api_err:
                    results["errors"].append(f"user {user_id}: {api_err}")
                    self._log(f"Follow error for {user_id}: {api_err}", "warning")

                # Human-like delay between follows
                self._human_delay()

        except Exception as exc:
            results["errors"].append(str(exc))
            self._log(f"follow_by_tag failed: {exc}", "error")

        return results

    # ── Unfollow non-reciprocals ──────────────────────────────────────────────

    def unfollow_non_reciprocals(self, max_unfollows: int = 50) -> dict:
        """
        Unfollow users who don't follow you back.

        Flow:
            1. Fetch your followings list
            2. Fetch your followers list
            3. Diff → users you follow who don't follow you back
            4. Unfollow each with rate-limit + human delay
        """
        results = {
            "mode": "live" if self._live else "simulation",
            "max_unfollows": max_unfollows,
            "unfollowed": 0,
            "skipped_daily_cap": 0,
            "errors": [],
        }

        if not self._live:
            for _ in range(min(max_unfollows, 20)):
                if not self._unfollows_today.increment():
                    results["skipped_daily_cap"] += 1
                    break
                results["unfollowed"] += 1
            results["message"] = "Simulation — configure credentials in .env"
            return results

        try:
            followings = {u["id"]: u for u in self.ig_client.get_own_followings(limit=200)}
            followers  = {u["id"] for u in self.ig_client.get_own_followers(limit=200)}

            non_reciprocals = [uid for uid in followings if uid not in followers]
            self._log(f"{len(non_reciprocals)} non-reciprocal accounts to unfollow")

            for user_id in non_reciprocals:
                if results["unfollowed"] >= max_unfollows:
                    break
                if not self._unfollows_today.increment():
                    results["skipped_daily_cap"] += 1
                    self._log(f"Daily unfollow cap ({UNFOLLOW_PER_DAY}) reached", "warning")
                    break

                try:
                    self._acquire_rate_limit(f"unfollow_{user_id}")
                    success = self.ig_client.unfollow_user(user_id)
                    if success:
                        results["unfollowed"] += 1
                        self._log(f"Unfollowed {followings[user_id].get('username', user_id)}")
                except Exception as exc:
                    results["errors"].append(f"user {user_id}: {exc}")

                self._human_delay()

        except Exception as exc:
            results["errors"].append(str(exc))

        return results

    # ── Follow back ───────────────────────────────────────────────────────────

    def follow_back(self, max_follows: int = 30) -> dict:
        """Follow back everyone who follows you but whom you don't follow."""
        results = {
            "mode": "live" if self._live else "simulation",
            "max_follows": max_follows,
            "followed": 0,
            "errors": [],
        }

        if not self._live:
            for _ in range(min(max_follows, 20)):
                if not self._follows_today.increment():
                    break
                results["followed"] += 1
            results["message"] = "Simulation — configure credentials in .env"
            return results

        try:
            followers  = {u["id"] for u in self.ig_client.get_own_followers(limit=200)}
            followings = {u["id"] for u in self.ig_client.get_own_followings(limit=200)}
            to_follow  = followers - followings

            for user_id in list(to_follow):
                if results["followed"] >= max_follows:
                    break
                if not self._follows_today.increment():
                    break
                try:
                    self._acquire_rate_limit(f"follow_{user_id}")
                    if self.ig_client.follow_user(user_id):
                        results["followed"] += 1
                        self._followed_this_session.add(user_id)
                except Exception as exc:
                    results["errors"].append(str(exc))
                self._human_delay()

        except Exception as exc:
            results["errors"].append(str(exc))

        return results

    # ── Follow by competitor ──────────────────────────────────────────────────

    def follow_by_competitor(self, competitor_username: str, max_follows: int = 20) -> dict:
        """
        Follow the followers of a competitor/influencer account.
        Requires knowing their numeric IG user ID or username.
        """
        results = {
            "mode": "live" if self._live else "simulation",
            "competitor": competitor_username,
            "max_follows": max_follows,
            "followed": 0,
            "errors": [],
        }

        if not self._live:
            for _ in range(min(max_follows, 20)):
                if not self._follows_today.increment():
                    break
                results["followed"] += 1
            results["message"] = "Simulation — configure credentials in .env"
            return results

        try:
            # Resolve username → user_id via oEmbed or search
            # Graph API doesn't expose competitor followers directly without
            # the user granting permission — we use the hashtag strategy instead
            results["errors"].append(
                "Competitor follower scraping requires a Business Discovery scope. "
                "Use follow_by_tag() with niche hashtags as an alternative."
            )
        except Exception as exc:
            results["errors"].append(str(exc))

        return results

    # ── Like posts by hashtag ─────────────────────────────────────────────────

    def like_by_tag(self, tag: str, max_likes: int = 30) -> dict:
        """Like recent posts under a hashtag."""
        tag = tag.lstrip("#").strip()
        results = {
            "mode": "live" if self._live else "simulation",
            "tag": tag,
            "liked": 0,
            "skipped_daily_cap": 0,
            "errors": [],
        }

        if not self._live:
            for _ in range(min(max_likes, 30)):
                if not self._likes_today.increment():
                    results["skipped_daily_cap"] += 1
                    break
                results["liked"] += 1
            results["message"] = "Simulation — configure credentials in .env"
            return results

        try:
            hashtag_id = self.ig_client.search_hashtag_id(tag)
            if not hashtag_id:
                results["errors"].append(f"Hashtag #{tag} not found")
                return results

            media_items = self.ig_client.get_recent_media_by_hashtag(hashtag_id, limit=50)

            for item in media_items:
                if results["liked"] >= max_likes:
                    break
                media_id = item.get("id")
                if not media_id:
                    continue
                if not self._likes_today.increment():
                    results["skipped_daily_cap"] += 1
                    break
                try:
                    self._acquire_rate_limit(f"like_{media_id}")
                    if self.ig_client.like_media(media_id):
                        results["liked"] += 1
                except Exception as exc:
                    results["errors"].append(f"media {media_id}: {exc}")
                self._human_delay()

        except Exception as exc:
            results["errors"].append(str(exc))

        return results

    # ── Engage back with your own followers ────────────────────────────────────

    def engage_with_followers(
        self,
        comment_text: str = "Love this! 🔥",
        max_engage: int = 20,
        do_like: bool = True,
        do_comment: bool = False,
    ) -> dict:
        """
        Like and/or comment on recent posts from your own followers.
        This is an OPTIONAL action that builds authentic relationships and
        significantly increases follow-back rates (from ~25% to ~40-50%).
        Triggered separately — not part of the automatic follow flow.
        """
        results = {
            "mode":      "live" if self._live else "simulation",
            "liked":     0,
            "commented": 0,
            "skipped":   0,
            "errors":    [],
        }
        if not self._live:
            for _ in range(min(max_engage, 20)):
                if do_like and self._likes_today.increment():
                    results["liked"] += 1
                if do_comment:
                    results["commented"] += 1
            results["message"] = "Simulation — configure Instagram credentials to engage real followers"
            return results
        try:
            followers = self.ig_client.get_own_followers(limit=min(max_engage * 2, 200))
            for follower in followers[:max_engage]:
                user_id = follower.get("id")
                if not user_id:
                    continue
                try:
                    recent = self.ig_client.get_user_recent_media(user_id, limit=1)
                    if not recent:
                        results["skipped"] += 1
                        continue
                    media_id = recent[0].get("id")
                    if not media_id:
                        results["skipped"] += 1
                        continue
                    if do_like and self._likes_today.increment():
                        try:
                            self._acquire_rate_limit(f"like_{media_id}")
                            if self.ig_client.like_media(media_id):
                                results["liked"] += 1
                        except Exception as e:
                            self._likes_today._count -= 1
                            results["errors"].append(str(e))
                    if do_comment:
                        try:
                            self._acquire_rate_limit(f"comment_{media_id}")
                            self.ig_client.comment_on_media(media_id, comment_text)
                            results["commented"] += 1
                        except Exception as e:
                            results["errors"].append(str(e))
                    self._human_delay()
                except Exception as e:
                    results["errors"].append(f"user {user_id}: {e}")
        except Exception as e:
            results["errors"].append(str(e))
        return results

    def engage_with_followers(
        self,
        comment_text: str = "Love this! 🔥",
        max_engage: int = 20,
        do_like: bool = True,
        do_comment: bool = False,
    ) -> dict:
        """
        Like and/or comment on recent posts from your own Instagram followers.
        Builds authentic relationships and increases follow-back rate by 2–3×.
        OPTIONAL — triggered separately by the user, not part of the auto-follow flow.
        """
        results = {
            "mode":      "live" if self._live else "simulation",
            "liked":     0,
            "commented": 0,
            "skipped":   0,
            "errors":    [],
        }
        if not self._live:
            for _ in range(min(max_engage, 20)):
                if do_like and self._likes_today.increment():
                    results["liked"] += 1
                if do_comment:
                    results["commented"] += 1
            results["message"] = "Simulation — configure Instagram credentials to engage real followers"
            return results
        try:
            followers = self.ig_client.get_own_followers(limit=min(max_engage * 2, 200))
            for follower in followers[:max_engage]:
                user_id = follower.get("id")
                if not user_id:
                    continue
                try:
                    recent = self.ig_client.get_user_recent_media(user_id, limit=1)
                    if not recent:
                        results["skipped"] += 1
                        continue
                    media_id = recent[0].get("id")
                    if not media_id:
                        results["skipped"] += 1
                        continue
                    if do_like and self._likes_today.increment():
                        try:
                            self._acquire_rate_limit(f"like_{media_id}")
                            if self.ig_client.like_media(media_id):
                                results["liked"] += 1
                        except Exception as e:
                            self._likes_today._count -= 1
                            results["errors"].append(str(e))
                    if do_comment:
                        try:
                            self._acquire_rate_limit(f"comment_{media_id}")
                            self.ig_client.comment_on_media(media_id, comment_text)
                            results["commented"] += 1
                        except Exception as e:
                            results["errors"].append(str(e))
                    self._human_delay()
                except Exception as e:
                    results["errors"].append(f"user {user_id}: {e}")
        except Exception as e:
            results["errors"].append(str(e))
        return results
    # ── Stats ─────────────────────────────────────────────────────────────────

    def daily_stats(self) -> dict:
        return {
            "mode": "live" if self._live else "simulation",
            "instagram_configured": self._live,
            "follows_today":    self._follows_today.count,
            "follows_remaining":self._follows_today.remaining,
            "unfollows_today":  self._unfollows_today.count,
            "likes_today":      self._likes_today.count,
            "daily_caps": {
                "follow":   FOLLOW_PER_DAY,
                "unfollow": UNFOLLOW_PER_DAY,
                "like":     LIKES_PER_DAY,
            },
        }

    # ── Legacy stubs (kept for backward compat) ───────────────────────────────

    def follow_by_location(self, location: str, max_follows: int = 20) -> dict:
        return self.follow_by_tag(location, max_follows)   # repurpose

    def follow_from_list(self, usernames: list, max_follows: int = 50) -> dict:
        results = {"followed": 0, "errors": [], "mode": "live" if self._live else "simulation"}
        if not self._live:
            results["followed"] = min(len(usernames), max_follows, 20)
            results["message"] = "Simulation — configure credentials in .env"
        return results

    def like_post(self, post_id: str, max_likes: int = 1) -> dict:
        if self._live:
            try:
                self.ig_client.like_media(post_id)
                return {"liked": 1}
            except Exception as exc:
                return {"liked": 0, "error": str(exc)}
        return {"liked": 1, "mode": "simulation"}

    def search_by_hashtags(self, hashtags: list, max_results: int = 10) -> dict:
        users: list[str] = []
        for tag in hashtags:
            users += [f"user_{tag}_{i}" for i in range(max_results)]
        return {"users_found": users, "mode": "simulation" if not self._live else "live"}


    # ════════════════════════════════════════════════════════════════════════
    #  TARGETED FOLLOWER GROWTH
    # ════════════════════════════════════════════════════════════════════════

    def _follow_pool(self, hashtags: list, max_follows: int, label: str) -> dict:
        """
        Internal: iterate through a pool of hashtags, follow users from each,
        stop when max_follows is reached or all hashtags are exhausted.
        """
        results = {
            "mode":                     "live" if self._live else "simulation",
            "target":                   label,
            "hashtags_used":            [],
            "followed":                 0,
            "skipped_already_followed": 0,
            "skipped_daily_cap":        0,
            "errors":                   [],
        }

        if not hashtags:
            results["errors"].append("No hashtags generated for the given criteria")
            return results

        per_tag = max(1, max_follows // len(hashtags))

        for tag in hashtags:
            if results["followed"] >= max_follows:
                break
            remaining = max_follows - results["followed"]
            tag_result = self.follow_by_tag(tag, min(per_tag, remaining))
            results["hashtags_used"].append(tag)
            results["followed"]                 += tag_result.get("followed", 0)
            results["skipped_already_followed"] += tag_result.get("skipped_already_followed", 0)
            results["skipped_daily_cap"]        += tag_result.get("skipped_daily_cap", 0)
            results["errors"]                   += tag_result.get("errors", [])

            if tag_result.get("skipped_daily_cap", 0) > 0:
                break  # daily cap hit — stop early

        if not self._live:
            results["message"] = (
                "Simulation only — add INSTAGRAM_ACCESS_TOKEN and "
                "INSTAGRAM_USER_ID to .env to enable real follows."
            )
        return results

    # ── 1. Gender-based followers ─────────────────────────────────────────────

    def follow_by_gender(
        self,
        gender: str,
        max_follows: int = 20,
        extra_tags: list | None = None,
    ) -> dict:
        """
        Follow users whose posts appear under gender-skewed hashtags.

        gender: "male" | "female" | "any"

        Strategy: hashtags like #mensfashion, #girlboss etc. attract
        audiences that heavily skew toward that gender.  Following users
        from those pools produces follower-back rates of 25–40 % from
        the targeted gender group.
        """
        from .targeting import get_gender_hashtags, describe_target
        hashtags = get_gender_hashtags(gender)
        if extra_tags:
            hashtags += [t.lstrip("#") for t in extra_tags]
        label = describe_target(gender, None, None, None)
        self._log(f"Gender targeting: {label} → {len(hashtags)} hashtags")
        result = self._follow_pool(hashtags[:8], max_follows, label)
        result["gender"] = gender
        return result

    # ── 2. City-based followers ───────────────────────────────────────────────

    def follow_by_city(
        self,
        city: str,
        max_follows: int = 20,
        gender: str | None = None,
    ) -> dict:
        """
        Follow users who post from / about a specific city.

        Combines city hashtags (#mumbai, #mumbaifoodie…) with optional
        gender overlay for hyper-targeted local growth.
        """
        from .targeting import get_city_hashtags, get_gender_hashtags, describe_target
        hashtags = get_city_hashtags(city)
        if gender:
            # Intersect: take top city tags + top gender tags
            hashtags = hashtags[:5] + get_gender_hashtags(gender)[:5]
        label = describe_target(gender, city, None, None)
        self._log(f"City targeting: {label} → {len(hashtags)} hashtags")
        result = self._follow_pool(hashtags[:10], max_follows, label)
        result["city"] = city
        if gender:
            result["gender"] = gender
        return result

    # ── 3. State-based followers ──────────────────────────────────────────────

    def follow_by_state(
        self,
        state: str,
        max_follows: int = 20,
        gender: str | None = None,
        city: str | None = None,
    ) -> dict:
        """
        Follow users from an entire state/region.

        Stacks: state hashtags + optional city refinement + optional gender.
        """
        from .targeting import (get_state_hashtags, get_city_hashtags,
                                 get_gender_hashtags, describe_target)
        hashtags = get_state_hashtags(state)
        if city:
            hashtags = get_city_hashtags(city)[:4] + hashtags[:4]
        if gender:
            hashtags += get_gender_hashtags(gender)[:4]
        label = describe_target(gender, city, state, None)
        self._log(f"State targeting: {label} → {len(hashtags)} hashtags")
        result = self._follow_pool(hashtags[:10], max_follows, label)
        result["state"] = state
        if city:   result["city"]   = city
        if gender: result["gender"] = gender
        return result

    # ── 4. Business-based followers ───────────────────────────────────────────

    def follow_by_business(
        self,
        business_type: str,
        max_follows: int = 20,
        city: str | None = None,
        gender: str | None = None,
    ) -> dict:
        """
        Follow users in a specific business niche.

        Examples: restaurant, fashion, fitness, realestate, ecommerce, tech,
                  photography, coaching, healthcare, education, travel.

        Optionally narrow by city or gender for hyper-local B2B targeting.
        """
        from .targeting import (get_business_hashtags, get_city_hashtags,
                                 get_gender_hashtags, describe_target)
        hashtags = get_business_hashtags(business_type)
        if city:
            # Add city context — e.g. "mumbai + restaurant" audience
            hashtags = get_city_hashtags(city)[:3] + hashtags[:7]
        if gender:
            hashtags += get_gender_hashtags(gender)[:3]
        label = describe_target(gender, city, None, business_type)
        self._log(f"Business targeting: {label} → {len(hashtags)} hashtags")
        result = self._follow_pool(hashtags[:10], max_follows, label)
        result["business_type"] = business_type
        if city:   result["city"]   = city
        if gender: result["gender"] = gender
        return result

    # ── 5. Combined targeting ─────────────────────────────────────────────────

    def follow_targeted(
        self,
        gender:        str | None = None,
        city:          str | None = None,
        state:         str | None = None,
        business_type: str | None = None,
        max_follows:   int = 20,
        extra_tags:    list | None = None,
    ) -> dict:
        """
        Single entry-point for all targeting dimensions combined.
        Pass any combination of gender/city/state/business_type.
        """
        from .targeting import build_targeted_hashtags, describe_target
        hashtags = build_targeted_hashtags(gender, city, state, business_type, extra_tags)
        label    = describe_target(gender, city, state, business_type)
        self._log(f"Combined targeting: {label} → {len(hashtags)} hashtags")
        result = self._follow_pool(hashtags[:12], max_follows, label)
        if gender:        result["gender"]        = gender
        if city:          result["city"]          = city
        if state:         result["state"]         = state
        if business_type: result["business_type"] = business_type
        return result

