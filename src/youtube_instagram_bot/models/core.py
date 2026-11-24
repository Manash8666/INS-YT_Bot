"""Core enums and types for YouTube-Instagram Bot."""

import enum
from datetime import datetime
from typing import Optional


class Platform(enum.Enum):
    """Target platform for publishing."""
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    RUMBLE = "rumble"


class ContentType(enum.Enum):
    """Type of content."""
    IMAGE = "image"
    VIDEO = "video"
    TEXT = "text"


class ConversionTarget(enum.Enum):
    """Target platform for content conversion."""
    REEL = "reel"      # Instagram Reel: <= 90s, 9:16 portrait
    SHORT = "short"    # YouTube Short: <= 60s, 9:16 portrait


class AccountStatus(enum.Enum):
    """Status of an account."""
    AUTHORIZED = "authorized"
    UNAUTHORIZED = "unauthorized"


class JobStatus(enum.Enum):
    """Status of a job."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    PARTIALLY_COMPLETE = "partially_complete"
    FAILED = "failed"


class ActionStatus(enum.Enum):
    """Status of a platform action."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class LogLevel(enum.Enum):
    """Log verbosity levels."""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40


class Target:
    """Target for publishing."""
    def __init__(
        self,
        platform: Platform,
        account_id: str,
        mapping_id: Optional[str] = None,
    ):
        self.platform = platform
        self.account_id = account_id
        self.mapping_id = mapping_id


class Account:
    """Account entity."""
    def __init__(
        self,
        id: str,
        platform: Platform,
        status: AccountStatus,
        encrypted_credentials: bytes,
        encrypted_access_token: bytes,
        encrypted_refresh_token: bytes,
        token_expires_at: datetime,
        created_at: datetime,
    ):
        self.id = id
        self.platform = platform
        self.status = status
        self.encrypted_credentials = encrypted_credentials
        self.encrypted_access_token = encrypted_access_token
        self.encrypted_refresh_token = encrypted_refresh_token
        self.token_expires_at = token_expires_at
        self.created_at = created_at


class Content:
    """Content asset."""
    def __init__(
        self,
        id: str,
        type: ContentType,
        format: str,
        blob: bytes,
        metadata: dict,
        created_at: datetime,
    ):
        self.id = id
        self.type = type
        self.format = format
        self.blob = blob
        self.metadata = metadata
        self.created_at = created_at


class Token:
    """Access token."""
    def __init__(
        self,
        access_token: str,
        expires_at: datetime,
        refresh_token: Optional[str] = None,
    ):
        self.access_token = access_token
        self.expires_at = expires_at
        self.refresh_token = refresh_token


class RetryProfile:
    """Retry configuration profile."""
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


class LogEntry:
    """Log entry."""
    def __init__(
        self,
        id: str,
        timestamp: datetime,
        level: LogLevel,
        account_id: Optional[str],
        job_id: Optional[str],
        outcome: Optional[str],
        error_code: Optional[str],
        description: Optional[str],
        content_id: Optional[str],
    ):
        self.id = id
        self.timestamp = timestamp
        self.level = level
        self.account_id = account_id
        self.job_id = job_id
        self.outcome = outcome
        self.error_code = error_code
        self.description = description
        self.content_id = content_id
