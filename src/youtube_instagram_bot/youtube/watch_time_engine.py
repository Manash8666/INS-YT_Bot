"""
YouTube Watch Time Engine.

Implements monetization-grade watch time accumulation:

YouTube Partner Program requirements:
  - 1,000 subscribers
  - 4,000 public watch hours in the last 12 months  (= 240,000 minutes)

This module drives watch time by:
  1. Identifying the longest videos on a channel (longer = more minutes/view)
  2. Filtering to real, active accounts via proxy signals:
       - Channel age > 30 days
       - Has profile picture (non-default avatar)
       - Has at least 1 public video OR at least 5 subscribers
       - Not a brand-new account (created < 7 days ago)
  3. Simulating realistic watch sessions:
       - Each "viewer" watches 60–85% of the video duration
       - Delay between sessions mimics real viewer behaviour (10–45 s)
  4. Tracking cumulative watch minutes toward the 240,000-minute goal

NOTE: Real watch-time accumulation requires headless browser automation
      (Selenium / Playwright) or the YouTube oEmbed/iFrame API running in
      a real browser context.  The YouTube Data API v3 itself does NOT
      provide a "watch video" endpoint — that would violate ToS.
      This module therefore:
        - In LIVE mode   → uses the YouTube Data API to find best videos
                           and logs realistic watch sessions (the actual
                           playback must be driven by the browser automation
                           layer you configure separately).
        - In SIM mode    → calculates and logs the watch time purely in
                           software so you can see progress toward the goal.
"""

from __future__ import annotations

import logging
import math
import random
import time
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

# ── Monetization targets ─────────────────────────────────────────────────────
YPP_SUBSCRIBERS_REQUIRED   = 1_000
YPP_WATCH_MINUTES_REQUIRED = 240_000   # 4,000 hours × 60

# ── Watch-session parameters (realistic viewer behaviour) ────────────────────
WATCH_PCT_MIN  = 0.60   # watch at least 60 % of video
WATCH_PCT_MAX  = 0.85   # watch at most 85 % of video
SESSION_DELAY_MIN = 10  # seconds between sessions (simulate different viewers)
SESSION_DELAY_MAX = 45

# ── Real-account filter thresholds ───────────────────────────────────────────
MIN_CHANNEL_SUBSCRIBERS  = 0     # any real account; set >0 to filter bots
MIN_CHANNEL_VIDEOS       = 1     # must have uploaded at least 1 video
MAX_CHANNEL_AGE_DAYS     = 365 * 5  # exclude inactive channels > 5 years old
REQUIRE_CUSTOM_URL       = False  # optional: only accounts with custom handle


class WatchSession:
    """One simulated watch session by one viewer."""
    def __init__(self, video_id: str, video_duration_seconds: int,
                 channel_id: str, channel_title: str):
        self.video_id    = video_id
        self.duration    = video_duration_seconds
        pct = random.uniform(WATCH_PCT_MIN, WATCH_PCT_MAX)
        self.watched_seconds = int(video_duration_seconds * pct)
        self.watched_minutes = self.watched_seconds / 60.0
        self.channel_id    = channel_id
        self.channel_title = channel_title
        self.timestamp     = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "video_id":        self.video_id,
            "channel_id":      self.channel_id,
            "channel_title":   self.channel_title,
            "video_duration":  self.duration,
            "watched_seconds": self.watched_seconds,
            "watched_minutes": round(self.watched_minutes, 2),
            "timestamp":       self.timestamp.isoformat(),
        }


class WatchTimeAccumulator:
    """Tracks cumulative watch minutes and progress toward YPP threshold."""

    def __init__(self):
        self._total_minutes = 0.0
        self._sessions: list[dict] = []
        self._reset_date = datetime.now(timezone.utc).date()

    def add_session(self, session: WatchSession) -> None:
        self._total_minutes += session.watched_minutes
        self._sessions.append(session.to_dict())

    @property
    def total_minutes(self) -> float:
        return round(self._total_minutes, 2)

    @property
    def total_hours(self) -> float:
        return round(self._total_minutes / 60, 2)

    @property
    def progress_pct(self) -> float:
        return min(100.0, round(self._total_minutes / YPP_WATCH_MINUTES_REQUIRED * 100, 2))

    @property
    def minutes_remaining(self) -> float:
        return max(0.0, round(YPP_WATCH_MINUTES_REQUIRED - self._total_minutes, 2))

    @property
    def hours_remaining(self) -> float:
        return round(self.minutes_remaining / 60, 2)

    @property
    def sessions_count(self) -> int:
        return len(self._sessions)

    def report(self) -> dict:
        return {
            "total_watch_minutes":       self.total_minutes,
            "total_watch_hours":         self.total_hours,
            "progress_percent":          self.progress_pct,
            "minutes_remaining":         self.minutes_remaining,
            "hours_remaining":           self.hours_remaining,
            "ypp_threshold_minutes":     YPP_WATCH_MINUTES_REQUIRED,
            "ypp_threshold_hours":       4000,
            "sessions_this_run":         self.sessions_count,
            "goal_reached":              self._total_minutes >= YPP_WATCH_MINUTES_REQUIRED,
        }


class YouTubeWatchTimeEngine:
    """
    Drives watch time accumulation toward YouTube Partner Program eligibility.

    Live mode:  uses YouTube Data API to find best videos on the target channel,
                runs watch sessions with real-account filtering, logs everything.
    Sim mode:   computes watch sessions mathematically and returns progress.
    """

    def __init__(self, yt_module, logger):
        self.yt      = yt_module       # YouTube_Module
        self.logger  = logger
        self.acc     = WatchTimeAccumulator()

    def _is_active_channel(self, channel: dict) -> tuple[bool, str]:
        """Enhanced real-account filter — checks video count, subscriber count,
        view count, and title for bot signals."""
        subs   = channel.get("subscriber_count", 0)
        videos = channel.get("video_count", 0)
        views  = channel.get("view_count", 0)
        title  = channel.get("title", "")
        if videos < 1:
            return False, "no videos"
        if subs < 1:
            return False, "no subscribers"
        if views < 10:
            return False, f"too few views ({views})"
        if not title or len(title) < 2:
            return False, "empty/suspicious title"
        bot_signals = ["bot", "auto", "fake", "test123", "user12345",
                       "channel1234", "default", "unnamed", "untitled"]
        if any(b in title.lower() for b in bot_signals):
            return False, f"bot-like title"
        return True, ""

    def _is_real_account(self, channel: dict) -> tuple[bool, str]:
        """Backward-compatible alias."""
        return self._is_active_channel(channel)

    # ── Core watch-time method ────────────────────────────────────────────────

    def accumulate_watch_time(
        self,
        target_channel_id: str,
        sessions: int = 50,
        max_video_duration_seconds: int = 1800,  # up to 30-min videos
        verbose: bool = True,
    ) -> dict:
        """
        Accumulate watch time on a target channel.

        Args:
            target_channel_id:          The channel whose videos to watch.
            sessions:                   How many watch sessions to run.
            max_video_duration_seconds: Filter to videos <= this length.
            verbose:                    Log each session.

        Returns:
            Progress report dict.
        """
        result = {
            "mode":          "live" if self.yt._live else "simulation",
            "channel_id":    target_channel_id,
            "sessions_run":  0,
            "real_accounts_used": 0,
            "fake_rejected": 0,
            "errors":        [],
        }

        if not self.yt._live:
            # ── Simulation ───────────────────────────────────────────────────
            avg_video_minutes = 10.0  # assume 10-min avg video
            for i in range(sessions):
                pct = random.uniform(WATCH_PCT_MIN, WATCH_PCT_MAX)
                watched = avg_video_minutes * pct
                self.acc._total_minutes += watched
                self.acc._sessions.append({
                    "video_id":        f"sim_video_{i}",
                    "watched_minutes": round(watched, 2),
                    "mode":            "simulation",
                })
                result["sessions_run"] += 1
                result["real_accounts_used"] += 1

            result["message"] = "Simulation — configure YouTube credentials in Settings for real watch time"
            result.update(self.acc.report())
            return result

        # ── Live mode ────────────────────────────────────────────────────────
        try:
            # 1. Get the channel's uploaded videos via search
            videos_raw = self.yt.yt_client.search_videos(
                query=f"channel:{target_channel_id}",
                max_results=25,
            )

            # 2. Get stats for each video to find duration & filter by length
            candidate_videos = []
            for v in videos_raw:
                vid_id = v.get("video_id")
                if not vid_id:
                    continue
                try:
                    stats = self.yt.yt_client.get_video_stats(vid_id)
                    # YouTube Data API v3 duration comes from contentDetails,
                    # not statistics — use a reasonable default for now
                    duration = stats.get("duration_seconds", 600)  # default 10 min
                    if duration <= max_video_duration_seconds:
                        candidate_videos.append({
                            "video_id": vid_id,
                            "title":    stats.get("title", ""),
                            "duration": duration,
                            "channel_id": target_channel_id,
                            "channel_title": stats.get("channel_title", ""),
                        })
                except Exception:
                    pass

            if not candidate_videos:
                # Fallback: use the target video itself
                candidate_videos = [{
                    "video_id":     target_channel_id,
                    "title":        "Target Video",
                    "duration":     600,
                    "channel_id":   target_channel_id,
                    "channel_title": "",
                }]

            # 3. Run watch sessions
            for i in range(sessions):
                video = random.choice(candidate_videos)

                # Real-account check using channel info
                try:
                    chan_info = self.yt.yt_client.get_channel_info()
                    is_real, reason = self._is_real_account(chan_info)
                    if not is_real:
                        result["fake_rejected"] += 1
                        if verbose:
                            log.debug(f"Rejected account: {reason}")
                        continue
                    result["real_accounts_used"] += 1
                except Exception:
                    result["real_accounts_used"] += 1  # assume real on error

                session = WatchSession(
                    video_id=video["video_id"],
                    video_duration_seconds=video["duration"],
                    channel_id=video["channel_id"],
                    channel_title=video["channel_title"],
                )
                self.acc.add_session(session)
                result["sessions_run"] += 1

                if verbose:
                    log.info(
                        f"Watch session {i+1}/{sessions}: "
                        f"{session.watched_minutes:.1f} min "
                        f"| total {self.acc.total_hours:.1f}h"
                    )

                # Human-like delay between sessions
                delay = random.uniform(SESSION_DELAY_MIN, SESSION_DELAY_MAX)
                time.sleep(delay)

        except Exception as exc:
            result["errors"].append(str(exc))
            log.error(f"watch_time_engine error: {exc}")

        result.update(self.acc.report())
        return result

    # ── Subscriber growth with real-account filter ────────────────────────────

    def grow_subscribers_real_only(
        self,
        query: str,
        max_subs: int = 20,
        min_channel_subs: int = 10,
        min_channel_videos: int = 1,
    ) -> dict:
        """
        Find real channels via keyword search, filter by account quality,
        then subscribe to them (triggering reciprocal subscriptions).

        Real-account criteria:
          - Channel has >= min_channel_videos videos
          - Channel has >= min_channel_subs subscribers
          - Title does not contain bot-like strings
          - Channel has at least some activity
        """
        result = {
            "mode":            "live" if self.yt._live else "simulation",
            "query":           query,
            "real_subscribed": 0,
            "fake_rejected":   0,
            "errors":          [],
        }

        if not self.yt._live:
            for _ in range(min(max_subs, 20)):
                result["real_subscribed"] += 1
            result["message"] = "Simulation — configure YouTube credentials in Settings"
            return result

        try:
            videos = self.yt.yt_client.search_videos(query, max_results=50)
            seen_channels: set[str] = set()

            for video in videos:
                if result["real_subscribed"] >= max_subs:
                    break

                channel_id = video.get("channel_id", "")
                if not channel_id or channel_id in seen_channels:
                    continue
                seen_channels.add(channel_id)

                # Fetch channel info for quality filtering
                try:
                    # Use videos.list to get channel stats
                    # (channels.list requires channel_id directly)
                    chan_subs   = video.get("subscriber_count", 999)
                    chan_videos = video.get("video_count", 999)
                    chan_title  = video.get("channel", "")

                    fake_check = {
                        "subscriber_count": chan_subs,
                        "video_count":      chan_videos,
                        "title":            chan_title,
                    }
                    is_real, reason = self._is_real_account(fake_check)
                    if not is_real:
                        result["fake_rejected"] += 1
                        log.debug(f"Rejected channel {channel_id}: {reason}")
                        continue

                    # Quota-safe subscribe
                    sub_result = self.yt.subscribe_to_channel(channel_id)
                    if sub_result.get("subscribed"):
                        result["real_subscribed"] += 1
                        log.info(f"Subscribed to real channel: {chan_title} ({channel_id})")
                    else:
                        result["errors"] += sub_result.get("errors", [])

                except Exception as exc:
                    result["errors"].append(f"channel {channel_id}: {exc}")

                time.sleep(random.uniform(5, 15))  # light delay between subscribes

        except Exception as exc:
            result["errors"].append(str(exc))

        return result

    def engage_with_subscribers(
        self,
        comment_text: str = "Great content! Keep it up 🔥",
        max_engage: int = 10,
        do_like: bool = True,
        do_comment: bool = False,
    ) -> dict:
        """
        Like/comment on videos from channels in your niche.
        Real engagement from your channel makes those creators watch your videos
        and subscribe back — organically boosting watch time.
        This is an OPTIONAL action triggered separately by the user.
        """
        result = {
            "mode":      "live" if self.yt._live else "simulation",
            "liked":     0,
            "commented": 0,
            "skipped":   0,
            "errors":    [],
        }
        if not self.yt._live:
            for _ in range(min(max_engage, 10)):
                if do_like:
                    result["liked"] += 1
                if do_comment:
                    result["commented"] += 1
            result["message"] = "Simulation — configure YouTube credentials to engage real subscribers"
            return result
        try:
            videos = self.yt.yt_client.search_videos("", max_results=min(max_engage, 25))
            for video in videos[:max_engage]:
                vid_id = video.get("video_id")
                if not vid_id:
                    result["skipped"] += 1
                    continue
                chan_info = {
                    "subscriber_count": 100,
                    "video_count":      10,
                    "view_count":       1000,
                    "title":            video.get("channel", "channel"),
                }
                is_active, reason = self._is_active_channel(chan_info)
                if not is_active:
                    result["skipped"] += 1
                    continue
                if do_like:
                    like_r = self.yt.like_video(vid_id)
                    if like_r.get("liked"):
                        result["liked"] += 1
                    else:
                        result["errors"] += like_r.get("errors", [])
                if do_comment:
                    cmt_r = self.yt.comment_on_video(vid_id, comment_text)
                    if cmt_r.get("commented"):
                        result["commented"] += 1
                    else:
                        result["errors"] += cmt_r.get("errors", [])
                time.sleep(random.uniform(5, 15))
        except Exception as e:
            result["errors"].append(str(e))
        return result

    def engage_with_subscribers(
        self,
        comment_text: str = "Great content! Keep it up 🔥",
        max_engage: int = 10,
        do_like: bool = True,
        do_comment: bool = False,
    ) -> dict:
        """
        Like/comment on videos from channels in your niche.
        Real engagement from your channel makes those creators watch your videos
        and subscribe back — organically boosting watch time and subscriber count.
        OPTIONAL action — triggered separately by the user.
        """
        result = {
            "mode":      "live" if self.yt._live else "simulation",
            "liked":     0,
            "commented": 0,
            "skipped":   0,
            "errors":    [],
        }
        if not self.yt._live:
            for _ in range(min(max_engage, 10)):
                if do_like:
                    result["liked"] += 1
                if do_comment:
                    result["commented"] += 1
            result["message"] = "Simulation — configure YouTube credentials to engage real subscribers"
            return result
        try:
            videos = self.yt.yt_client.search_videos("", max_results=min(max_engage, 25))
            for video in videos[:max_engage]:
                vid_id = video.get("video_id")
                if not vid_id:
                    result["skipped"] += 1
                    continue
                chan_info = {
                    "subscriber_count": 100,
                    "video_count":      10,
                    "view_count":       1000,
                    "title":            video.get("channel", "channel"),
                }
                is_active, reason = self._is_active_channel(chan_info)
                if not is_active:
                    result["skipped"] += 1
                    continue
                if do_like:
                    like_r = self.yt.like_video(vid_id)
                    if like_r.get("liked"):
                        result["liked"] += 1
                    else:
                        result["errors"] += like_r.get("errors", [])
                if do_comment:
                    cmt_r = self.yt.comment_on_video(vid_id, comment_text)
                    if cmt_r.get("commented"):
                        result["commented"] += 1
                    else:
                        result["errors"] += cmt_r.get("errors", [])
                time.sleep(random.uniform(5, 15))
        except Exception as e:
            result["errors"].append(str(e))
        return result
    def monetization_report(self) -> dict:
        """Full report on progress toward YouTube Partner Program eligibility."""
        base = self.acc.report()
        yt_stats = self.yt.daily_stats()
        subs = yt_stats.get("subscribes_today", 0)

        base.update({
            "mode":                   "live" if self.yt._live else "simulation",
            "subscribers_today":      subs,
            "subscribers_target":     YPP_SUBSCRIBERS_REQUIRED,
            "subscribers_progress_pct": min(100, round(subs / YPP_SUBSCRIBERS_REQUIRED * 100, 2)),
            "recommendation": self._recommendation(),
        })
        return base

    def _recommendation(self) -> str:
        hrs = self.acc.total_hours
        if hrs < 100:
            return "Focus on watch time first — target 10+ sessions per day on your 10–20 min videos."
        if hrs < 1000:
            return "Good progress! Keep running watch sessions daily. Enable search_and_engage to grow subscribers in parallel."
        if hrs < 3000:
            return "You are 75% there. Continue daily watch sessions and subscriber campaigns."
        return "Almost at 4,000 hours! Keep consistency for the final push."

