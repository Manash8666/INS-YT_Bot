"""Retry_Handler with exponential backoff for transient failures."""

import time
from typing import Callable, Optional, TypeVar

from ..models.core import LogLevel
from ..exceptions import RetryExhaustedError


T = TypeVar("T")


class RetryProfile:
    """Configuration profile for retry behavior."""
    def __init__(
        self,
        max_retries: int,
        initial_delay: float,
        max_delay: float,
        multiplier: float,
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier


# Predefined retry profiles
PROFILE_YOUTUBE = RetryProfile(
    max_retries=3,
    initial_delay=2.0,
    max_delay=60.0,
    multiplier=2.0,
)

PROFILE_INSTAGRAM = RetryProfile(
    max_retries=3,
    initial_delay=2.0,
    max_delay=60.0,
    multiplier=2.0,
)

PROFILE_GENERAL = RetryProfile(
    max_retries=5,
    initial_delay=1.0,
    max_delay=60.0,
    multiplier=2.0,
)

PROFILE_TOKEN_REFRESH = RetryProfile(
    max_retries=3,
    initial_delay=1.0,
    max_delay=60.0,
    multiplier=2.0,
)


class Retry_Handler:
    """Retry handler with exponential backoff for transient failures.
    
    Uses parameterized profiles for different operation types.
    Stops immediately on permanent errors.
    """
    
    def __init__(self):
        """Initialize Retry_Handler."""
        pass
    
    def _calculate_delay(self, attempt: int, profile: RetryProfile) -> float:
        """Calculate delay for a given attempt using exponential backoff.
        
        Args:
            attempt: Attempt number (0-indexed)
            profile: Retry profile configuration
            
        Returns:
            Delay in seconds (monotonic, capped at max_delay)
        """
        # delay(n) = min(initial_delay * multiplier^(n-1), max_delay)
        if attempt == 0:
            delay = profile.initial_delay
        else:
            delay = profile.initial_delay * (profile.multiplier ** (attempt - 1))
        
        return min(delay, profile.max_delay)
    
    def _sleep_with_backoff(self, attempt: int, profile: RetryProfile) -> None:
        """Sleep with exponential backoff delay.
        
        Args:
            attempt: Attempt number (0-indexed)
            profile: Retry profile configuration
        """
        delay = self._calculate_delay(attempt, profile)
        time.sleep(delay)
    
    def execute(
        self,
        operation: Callable[[], T],
        profile: RetryProfile,
        is_transient: Callable[[Exception], bool],
        is_permanent: Callable[[Exception], bool],
        context: Optional[dict] = None,
    ) -> T:
        """Execute operation with exponential backoff retry.
        
        Retries transient errors up to profile.max_retries, stops immediately
        on permanent errors.
        
        Args:
            operation: Callable that performs the operation
            profile: Retry profile configuration
            is_transient: Function to classify transient errors
            is_permanent: Function to classify permanent errors
            context: Optional context dictionary for logging
            
        Returns:
            Result of the operation
            
        Raises:
            RetryExhaustedError: If all retry attempts are exhausted
        """
        last_exception = None
        
        for attempt in range(profile.max_retries + 1):  # +1 for initial attempt
            try:
                return operation()
            except Exception as e:
                last_exception = e
                
                if is_permanent(e):
                    # Stop immediately on permanent errors
                    raise
                
                if attempt < profile.max_retries:
                    # Sleep with backoff before retrying
                    self._sleep_with_backoff(attempt, profile)
                else:
                    # All retries exhausted
                    raise RetryExhaustedError(cause=e)
        
        # Should never reach here, but just in case
        raise RetryExhaustedError(cause=last_exception or Exception("Unknown error"))
