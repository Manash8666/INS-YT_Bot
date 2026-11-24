"""Exception hierarchy for YouTube-Instagram Bot."""

from typing import Optional


class BotError(Exception):
    """Base exception for all bot errors."""
    pass


class UnauthorizedError(BotError):
    """Account is not authorized."""
    def __init__(self, account_id: str):
        self.account_id = account_id
        super().__init__(f"Account {account_id} is not authorized")


class UnsupportedFormatError(BotError):
    """Unsupported content format."""
    def __init__(self, fmt: str):
        self.fmt = fmt
        super().__init__(f"Unsupported format: {fmt}")


class ConversionError(BotError):
    """Content conversion failed."""
    pass


class InvalidContentError(BotError):
    """Content is invalid or missing."""
    pass


class CaptionTooLongError(BotError):
    """Caption exceeds maximum length."""
    def __init__(self, max_length: int):
        self.max_length = max_length
        super().__init__(f"Caption exceeds maximum length of {max_length} characters")


class ThumbnailError(BotError):
    """Thumbnail attachment failed."""
    pass


class RetryExhaustedError(BotError):
    """All retry attempts exhausted."""
    def __init__(self, cause: Exception):
        self.cause = cause
        super().__init__(f"Retry exhausted: {cause}")


class StorageUnavailableError(BotError):
    """Storage service unavailable."""
    pass


class RateLimitPausedError(BotError):
    """Rate limit is paused for platform."""
    def __init__(self, platform: str, paused_until: float):
        self.platform = platform
        self.paused_until = paused_until
        super().__init__(f"Rate limit paused for {platform} until {paused_until}")
