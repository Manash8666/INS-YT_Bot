"""Rate_Limiter with sliding-window-log for platform rate limiting."""

import time
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from ..models.core import Platform
from ..storage.storage import Storage
from ..exceptions import RateLimitPausedError


class Rate_Limiter:
    """Rate limiter using sliding-window-log with per-account spacing.
    
    Tracks requests per platform and enforces minimum spacing between
    posts to same account.
    """
    
    def __init__(self, storage: Storage):
        """Initialize Rate_Limiter.
        
        Args:
            storage: Storage layer for persisting rate limit state
        """
        self.storage = storage
        # In-memory configuration: {platform: {"window": int, "max_requests": int}}
        self._config: dict = {}
        # In-memory request timestamps: {platform: [datetime]}
        self._timestamps: dict = defaultdict(list)
    
    def configure(self, platform: Platform, window: int, max_requests: int) -> None:
        """Configure rate limit for a platform.
        
        Args:
            platform: Platform (youtube, instagram, rumble)
            window: Window duration in seconds (1-3600)
            max_requests: Maximum requests per window
        """
        if not (1 <= window <= 3600):
            raise ValueError(f"Window must be between 1 and 3600 seconds, got {window}")
        
        self._config[platform] = {
            "window": window,
            "max_requests": max_requests,
        }
        self._timestamps[platform] = []  # Clear existing timestamps
    
    def acquire(self, platform: Platform, account_id: str) -> None:
        """Block until a request slot is available for the platform.
        
        Enforces 1-second minimum spacing between posts to same account.
        
        Args:
            platform: Platform
            account_id: Account identifier
            
        Raises:
            RateLimitPausedError: If platform is paused due to rate limit
        """
        # Check if platform is paused
        state = self.storage.load_rate_limit_state(platform)
        if state.paused_until and datetime.utcnow() < state.paused_until:
            raise RateLimitPausedError(
                platform=platform.value,
                paused_until=state.paused_until.timestamp(),
            )
        
        # Get config for platform
        config = self._config.get(platform, {"window": 60, "max_requests": 100})
        window_seconds = config["window"]
        max_requests = config["max_requests"]
        
        # Prune old timestamps outside the window
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=window_seconds)
        self._timestamps[platform] = [
            ts for ts in self._timestamps[platform] if ts > window_start
        ]
        
        # Check if within capacity
        if len(self._timestamps[platform]) >= max_requests:
            # Calculate delay until oldest timestamp leaves the window
            oldest = min(self._timestamps[platform])
            delay = (oldest + timedelta(seconds=window_seconds) - now).total_seconds()
            if delay > 0:
                time.sleep(min(delay, 1.0))  # Wait up to 1 second
        
        # Check per-account minimum spacing (1 second)
        last_post = self.storage.last_post_time(account_id)
        if last_post:
            elapsed = (now - last_post).total_seconds()
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
        
        # Record this request
        self._timestamps[platform].append(now)
        self.storage.update_last_post_time(account_id, now)
    
    def handle_rate_limit_error(self, platform: Platform, retry_after: Optional[int] = None) -> None:
        """Pause requests to the platform after a rate limit error.
        
        Args:
            platform: Platform
            retry_after: Seconds to wait (None means default 60 seconds)
        """
        pause_seconds = retry_after if retry_after is not None else 60
        paused_until = datetime.utcnow() + timedelta(seconds=pause_seconds)
        
        state = self.storage.load_rate_limit_state(platform)
        state.paused_until = paused_until
        state.request_timestamps = []  # Clear timestamps on pause
        self.storage.save_rate_limit_state(state)
        
        # Clear in-memory timestamps
        self._timestamps[platform] = []
    
    def remaining(self, platform: Platform) -> int:
        """Get remaining capacity in the current window.
        
        Args:
            platform: Platform
            
        Returns:
            Number of remaining requests allowed
        """
        config = self._config.get(platform, {"window": 60, "max_requests": 100})
        max_requests = config["max_requests"]
        
        # Prune old timestamps
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=config["window"])
        self._timestamps[platform] = [
            ts for ts in self._timestamps[platform] if ts > window_start
        ]
        
        return max(0, max_requests - len(self._timestamps[platform]))
