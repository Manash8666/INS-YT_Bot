"""SQLAlchemy ORM models for Storage layer."""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import uuid4

from sqlalchemy import (
    Column, String, DateTime, Integer, Enum, LargeBinary, JSON, Boolean,
    ForeignKey, PrimaryKeyConstraint
)
from sqlalchemy.orm import declarative_base, relationship

from ..models.core import (
    Platform, ContentType, AccountStatus, JobStatus, ActionStatus, LogLevel
)

Base = declarative_base()


class AccountTable(Base):
    """ORM model for Account entity."""
    __tablename__ = "accounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    platform = Column(Enum(Platform), nullable=False)
    status = Column(Enum(AccountStatus), nullable=False)
    encrypted_credentials = Column(LargeBinary, nullable=False)
    encrypted_access_token = Column(LargeBinary, nullable=False)
    encrypted_refresh_token = Column(LargeBinary, nullable=False)
    token_expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False)

    def to_model(self) -> "Account":
        """Convert to domain model."""
        from ..models.value_objects import Account
        return Account(
            id=self.id,
            platform=self.platform,
            status=self.status,
            encrypted_credentials=self.encrypted_credentials,
            encrypted_access_token=self.encrypted_access_token,
            encrypted_refresh_token=self.encrypted_refresh_token,
            token_expires_at=self.token_expires_at,
            created_at=self.created_at,
        )


class ContentTable(Base):
    """ORM model for Content entity."""
    __tablename__ = "contents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    type = Column(Enum(ContentType), nullable=False)
    format = Column(String(50), nullable=False)
    blob = Column(LargeBinary, nullable=False)
    meta = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False)

    def to_model(self) -> "Content":
        """Convert to domain model."""
        from ..models.value_objects import Content
        return Content(
            id=self.id,
            type=self.type,
            format=self.format,
            blob=self.blob,
            metadata=self.meta,
            created_at=self.created_at,
        )


class JobTable(Base):
    """ORM model for Job entity."""
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scheduled_time = Column(DateTime, nullable=False)
    created_seq = Column(Integer, nullable=False)
    status = Column(Enum(JobStatus), nullable=False)
    source_content_id = Column(String(36), nullable=False)

    # Relationship to actions
    actions = relationship("JobActionTable", back_populates="job", cascade="all, delete-orphan")

    def to_model(self) -> "Job":
        """Convert to domain model."""
        from ..models.value_objects import Job, JobAction
        return Job(
            id=self.id,
            scheduled_time=self.scheduled_time,
            created_seq=self.created_seq,
            status=self.status,
            source_content_id=self.source_content_id,
            actions=[a.to_model() for a in self.actions],
        )


class JobActionTable(Base):
    """ORM model for JobAction entity."""
    __tablename__ = "job_actions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    platform = Column(Enum(Platform), nullable=False)
    account_id = Column(String(255), nullable=False)
    content_id = Column(String(36), nullable=False)
    status = Column(Enum(ActionStatus), nullable=False)
    post_id = Column(String(255), nullable=True)
    dispatch_attempts = Column(Integer, nullable=False, default=0)
    mapping_id = Column(String(255), nullable=True)

    # Relationship to job
    job = relationship("JobTable", back_populates="actions")

    def to_model(self) -> "JobAction":
        """Convert to domain model."""
        from ..models.value_objects import JobAction
        return JobAction(
            id=self.id,
            job_id=self.job_id,
            platform=self.platform,
            account_id=self.account_id,
            content_id=self.content_id,
            status=self.status,
            post_id=self.post_id,
            dispatch_attempts=self.dispatch_attempts,
            mapping_id=self.mapping_id,
        )


class PostTable(Base):
    """ORM model for Post entity."""
    __tablename__ = "posts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    platform = Column(Enum(Platform), nullable=False)
    platform_post_id = Column(String(255), nullable=False)
    content_id = Column(String(36), nullable=False)
    account_id = Column(String(255), nullable=False)
    published_at = Column(DateTime, nullable=False)

    def to_model(self) -> "Post":
        """Convert to domain model."""
        from ..models.value_objects import Post
        return Post(
            id=self.id,
            platform=self.platform,
            platform_post_id=self.platform_post_id,
            content_id=self.content_id,
            account_id=self.account_id,
            published_at=self.published_at,
        )


class DedupKeyTable(Base):
    """ORM model for DedupKey entity (composite PK)."""
    __tablename__ = "dedup_keys"

    content_id = Column(String(36), primary_key=True, nullable=False)
    platform = Column(Enum(Platform), primary_key=True, nullable=False)
    post_id = Column(String(255), nullable=False)

    def to_model(self) -> "DedupKey":
        """Convert to domain model."""
        from ..models.value_objects import DedupKey
        return DedupKey(
            content_id=self.content_id,
            platform=self.platform,
            post_id=self.post_id,
        )


class LogEntryTable(Base):
    """ORM model for LogEntry entity."""
    __tablename__ = "log_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    timestamp = Column(DateTime, nullable=False)
    level = Column(Enum(LogLevel), nullable=False)
    account_id = Column(String(255), nullable=True)
    job_id = Column(String(36), nullable=True)
    outcome = Column(String(50), nullable=True)
    error_code = Column(String(100), nullable=True)
    description = Column(String, nullable=True)
    content_id = Column(String(36), nullable=True)

    def to_model(self) -> "LogEntry":
        """Convert to domain model."""
        from ..models.value_objects import LogEntry
        return LogEntry(
            id=self.id,
            timestamp=self.timestamp,
            level=self.level,
            account_id=self.account_id,
            job_id=self.job_id,
            outcome=self.outcome,
            error_code=self.error_code,
            description=self.description,
            content_id=self.content_id,
        )


class RateLimitStateTable(Base):
    """ORM model for RateLimitState entity."""
    __tablename__ = "rate_limit_states"

    platform = Column(Enum(Platform), primary_key=True, nullable=False)
    request_timestamps = Column(JSON, nullable=False, default=list)
    paused_until = Column(DateTime, nullable=True)
    last_post_time = Column(DateTime, nullable=True)

    def to_model(self) -> "RateLimitState":
        """Convert to domain model."""
        from ..models.value_objects import RateLimitState
        from datetime import datetime
        
        # Convert ISO format strings back to datetime objects
        request_timestamps = []
        for ts in self.request_timestamps:
            if isinstance(ts, str):
                request_timestamps.append(datetime.fromisoformat(ts))
            else:
                request_timestamps.append(ts)
        
        paused_until = None
        if self.paused_until:
            if isinstance(self.paused_until, str):
                paused_until = datetime.fromisoformat(self.paused_until)
            else:
                paused_until = self.paused_until
        
        last_post_time = None
        if self.last_post_time:
            if isinstance(self.last_post_time, str):
                last_post_time = datetime.fromisoformat(self.last_post_time)
            else:
                last_post_time = self.last_post_time
        
        return RateLimitState(
            platform=self.platform,
            request_timestamps=request_timestamps,
            paused_until=paused_until,
            last_post_time=last_post_time,
        )


# Re-export ORM classes for convenience
__all__ = [
    "Base",
    "AccountTable",
    "ContentTable",
    "JobTable",
    "JobActionTable",
    "PostTable",
    "DedupKeyTable",
    "LogEntryTable",
    "RateLimitStateTable",
]
