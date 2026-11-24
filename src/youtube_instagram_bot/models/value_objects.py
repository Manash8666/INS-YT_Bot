"""Value objects for YouTube-Instagram Bot."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from .core import Platform, ContentType, AccountStatus, JobStatus, ActionStatus, LogLevel


@dataclass
class Target:
    """Target for publishing."""
    platform: Platform
    account_id: str
    mapping_id: Optional[str] = None


@dataclass
class Account:
    """Account entity."""
    id: str
    platform: Platform
    status: AccountStatus
    encrypted_credentials: bytes
    encrypted_access_token: bytes
    encrypted_refresh_token: bytes
    token_expires_at: datetime
    created_at: datetime


@dataclass
class Content:
    """Content asset."""
    id: str
    type: ContentType
    format: str
    blob: bytes
    metadata: dict
    created_at: datetime


@dataclass
class Token:
    """Access token."""
    access_token: str
    expires_at: datetime
    refresh_token: Optional[str] = None


@dataclass
class RetryProfile:
    """Retry configuration profile."""
    max_retries: int
    initial_delay: float
    max_delay: float
    multiplier: float


@dataclass
class JobAction:
    """Job action (platform-specific publish attempt)."""
    id: str
    job_id: str
    platform: Platform
    account_id: str
    content_id: str
    status: ActionStatus  # Should be ActionStatus, not JobStatus
    post_id: Optional[str]
    dispatch_attempts: int
    mapping_id: Optional[str] = None


@dataclass
class Job:
    """Job (collection of platform actions)."""
    id: str
    scheduled_time: datetime
    created_seq: int
    status: JobStatus
    source_content_id: str
    actions: List[JobAction]


@dataclass
class Post:
    """Post entity."""
    id: str
    platform: Platform
    platform_post_id: str
    content_id: str
    account_id: str
    published_at: datetime


@dataclass
class DedupKey:
    """Deduplication key."""
    content_id: str
    platform: Platform
    post_id: str


@dataclass
class LogEntry:
    """Log entry."""
    id: str
    timestamp: datetime
    level: LogLevel
    account_id: Optional[str]
    job_id: Optional[str]
    outcome: Optional[str]
    error_code: Optional[str]
    description: Optional[str]
    content_id: Optional[str]


@dataclass
class RateLimitState:
    """Rate limit state for a platform."""
    platform: Platform
    request_timestamps: List[datetime]
    paused_until: Optional[datetime]
    last_post_time: Optional[datetime] = None


@dataclass
class Credentials:
    """Credentials for platform authentication."""
    client_id: str
    client_secret: str
    refresh_token: Optional[str] = None
    token_uri: str = "https://oauth2.googleapis.com/token"
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "token_uri": self.token_uri,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Credentials":
        """Create from dictionary."""
        return cls(
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        )
    
    def to_bytes(self) -> bytes:
        """Convert to JSON bytes."""
        import json
        return json.dumps(self.to_dict()).encode("utf-8")
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "Credentials":
        """Create from JSON bytes."""
        import json
        return cls.from_dict(json.loads(data.decode("utf-8")))
