"""Storage layer for YouTube-Instagram Bot."""

import json
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import create_engine, select, and_, func, desc, update
from sqlalchemy.orm import sessionmaker

from .models import (
    Base,
    AccountTable,
    ContentTable,
    JobTable,
    JobActionTable,
    PostTable,
    DedupKeyTable,
    LogEntryTable,
    RateLimitStateTable,
)
from ..models.core import (
    Platform, ContentType, AccountStatus, JobStatus, ActionStatus, LogLevel
)
from ..models.value_objects import (
    Account, Content, Job, JobAction, Post, DedupKey, LogEntry, RateLimitState
)
from ..exceptions import StorageUnavailableError


class Storage:
    """Persistence layer using SQLAlchemy ORM with SQLite."""

    def __init__(self, connection_string: str = "sqlite:///bot.db"):
        """Initialize storage with connection string.
        
        Args:
            connection_string: SQLAlchemy connection string (default: SQLite)
        """
        try:
            self.engine = create_engine(connection_string, echo=False)
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            self._create_schema()
        except Exception as e:
            raise StorageUnavailableError(f"Failed to initialize storage: {e}")

    def _create_schema(self) -> None:
        """Create all tables in the database."""
        try:
            Base.metadata.create_all(bind=self.engine)
        except Exception as e:
            raise StorageUnavailableError(f"Failed to create schema: {e}")

    #region Content Methods

    def store_content(
        self,
        content_id: str,
        content_type: ContentType,
        fmt: str,
        blob: bytes,
        metadata: dict,
        created_at: Optional[datetime] = None,
    ) -> None:
        """Store content asset.
        
        Args:
            content_id: Unique content identifier
            content_type: Type of content (image, video, text)
            fmt: Format (jpeg, png, mp4, txt)
            blob: Raw asset bytes
            metadata: Arbitrary JSON metadata
            created_at: Creation timestamp (defaults to now)
        """
        if created_at is None:
            created_at = datetime.utcnow()
        
        session = self.SessionLocal()
        try:
            content = ContentTable(
                id=content_id,
                type=content_type,
                format=fmt,
                blob=blob,
                meta=metadata,
                created_at=created_at,
            )
            session.add(content)
            session.commit()
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to store content: {e}")
        finally:
            session.close()

    def read_content(self, content_id: str) -> bytes:
        """Read content bytes.
        
        Args:
            content_id: Unique content identifier
            
        Returns:
            Raw bytes of the content
            
        Raises:
            StorageUnavailableError: If content not found or database error
        """
        session = self.SessionLocal()
        try:
            content = session.query(ContentTable).filter(ContentTable.id == content_id).first()
            if content is None:
                raise StorageUnavailableError(f"Content not found: {content_id}")
            return content.blob
        except StorageUnavailableError:
            raise
        except Exception as e:
            raise StorageUnavailableError(f"Failed to read content: {e}")
        finally:
            session.close()

    def read_metadata(self, content_id: str) -> dict:
        """Read content metadata.
        
        Args:
            content_id: Unique content identifier
            
        Returns:
            Metadata dictionary
            
        Raises:
            StorageUnavailableError: If content not found or database error
        """
        session = self.SessionLocal()
        try:
            content = session.query(ContentTable).filter(ContentTable.id == content_id).first()
            if content is None:
                raise StorageUnavailableError(f"Content not found: {content_id}")
            return content.meta
        except StorageUnavailableError:
            raise
        except Exception as e:
            raise StorageUnavailableError(f"Failed to read metadata: {e}")
        finally:
            session.close()

    #endregion

    #region Account/Credential Methods

    def store_account(
        self,
        account_id: str,
        platform: Platform,
        status: AccountStatus,
        encrypted_creds: bytes,
        encrypted_access_token: bytes,
        encrypted_refresh_token: bytes,
        token_expires_at: datetime,
        created_at: Optional[datetime] = None,
    ) -> None:
        """Store account with encrypted credentials.
        
        Args:
            account_id: Unique account identifier
            platform: Platform (youtube, instagram)
            status: Authorization status
            encrypted_creds: Encrypted credentials blob
            encrypted_access_token: Encrypted access token
            encrypted_refresh_token: Encrypted refresh token
            token_expires_at: Token expiry time
            created_at: Creation timestamp (defaults to now)
        """
        if created_at is None:
            created_at = datetime.utcnow()
        
        session = self.SessionLocal()
        try:
            account = AccountTable(
                id=account_id,
                platform=platform,
                status=status,
                encrypted_credentials=encrypted_creds,
                encrypted_access_token=encrypted_access_token,
                encrypted_refresh_token=encrypted_refresh_token,
                token_expires_at=token_expires_at,
                created_at=created_at,
            )
            session.add(account)
            session.commit()
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to store account: {e}")
        finally:
            session.close()

    def load_account(self, account_id: str) -> Account:
        """Load account by ID.
        
        Args:
            account_id: Unique account identifier
            
        Returns:
            Account model object
            
        Raises:
            StorageUnavailableError: If account not found or database error
        """
        session = self.SessionLocal()
        try:
            account = session.query(AccountTable).filter(AccountTable.id == account_id).first()
            if account is None:
                raise StorageUnavailableError(f"Account not found: {account_id}")
            return account.to_model()
        except StorageUnavailableError:
            raise
        except Exception as e:
            raise StorageUnavailableError(f"Failed to load account: {e}")
        finally:
            session.close()

    def load_encrypted_creds(self, account_id: str) -> bytes:
        """Load encrypted credentials.
        
        Args:
            account_id: Unique account identifier
            
        Returns:
            Encrypted credentials blob
            
        Raises:
            StorageUnavailableError: If account not found or database error
        """
        session = self.SessionLocal()
        try:
            account = session.query(AccountTable).filter(AccountTable.id == account_id).first()
            if account is None:
                raise StorageUnavailableError(f"Account not found: {account_id}")
            return account.encrypted_credentials
        except StorageUnavailableError:
            raise
        except Exception as e:
            raise StorageUnavailableError(f"Failed to load encrypted credentials: {e}")
        finally:
            session.close()

    def update_account_status(self, account_id: str, status: AccountStatus) -> None:
        """Update account authorization status.
        
        Args:
            account_id: Unique account identifier
            status: New authorization status
        """
        session = self.SessionLocal()
        try:
            stmt = (
                update(AccountTable)
                .where(AccountTable.id == account_id)
                .values(status=status)
            )
            session.execute(stmt)
            session.commit()
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to update account status: {e}")
        finally:
            session.close()

    def store_encrypted_token(self, account_id: str, encrypted_token: bytes) -> None:
        """Store encrypted access token.
        
        Args:
            account_id: Unique account identifier
            encrypted_token: Encrypted access token
        """
        session = self.SessionLocal()
        try:
            account = session.query(AccountTable).filter(AccountTable.id == account_id).first()
            if account is None:
                raise StorageUnavailableError(f"Account not found: {account_id}")
            account.encrypted_access_token = encrypted_token
            session.commit()
        except StorageUnavailableError:
            raise
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to store encrypted token: {e}")
        finally:
            session.close()

    #endregion

    #region Job Methods

    def store_job(self, job: Job) -> None:
        """Store job with its actions.
        
        Args:
            job: Job model object
        """
        session = self.SessionLocal()
        try:
            job_table = JobTable(
                id=job.id,
                scheduled_time=job.scheduled_time,
                created_seq=job.created_seq,
                status=job.status,
                source_content_id=job.source_content_id,
            )
            
            for action in job.actions:
                action_table = JobActionTable(
                    id=action.id,
                    job_id=job.id,
                    platform=action.platform,
                    account_id=action.account_id,
                    content_id=action.content_id,
                    status=action.status,
                    post_id=action.post_id,
                    dispatch_attempts=action.dispatch_attempts,
                    mapping_id=action.mapping_id,
                )
                session.add(action_table)
            
            session.add(job_table)
            session.commit()
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to store job: {e}")
        finally:
            session.close()

    def load_job(self, job_id: str) -> Job:
        """Load job by ID.
        
        Args:
            job_id: Unique job identifier
            
        Returns:
            Job model object with actions
            
        Raises:
            StorageUnavailableError: If job not found or database error
        """
        session = self.SessionLocal()
        try:
            job = session.query(JobTable).filter(JobTable.id == job_id).first()
            if job is None:
                raise StorageUnavailableError(f"Job not found: {job_id}")
            return job.to_model()
        except StorageUnavailableError:
            raise
        except Exception as e:
            raise StorageUnavailableError(f"Failed to load job: {e}")
        finally:
            session.close()

    def update_job_status(self, job_id: str, status: JobStatus) -> None:
        """Update job status.
        
        Args:
            job_id: Unique job identifier
            status: New job status
        """
        session = self.SessionLocal()
        try:
            stmt = (
                update(JobTable)
                .where(JobTable.id == job_id)
                .values(status=status)
            )
            session.execute(stmt)
            session.commit()
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to update job status: {e}")
        finally:
            session.close()

    def update_action_status(
        self,
        job_id: str,
        platform: Platform,
        status: ActionStatus,
        post_id: Optional[str],
    ) -> None:
        """Update job action status.
        
        Args:
            job_id: Job identifier
            platform: Platform
            status: New action status
            post_id: Platform post ID on success
        """
        session = self.SessionLocal()
        try:
            action = (
                session.query(JobActionTable)
                .filter(
                    JobActionTable.job_id == job_id,
                    JobActionTable.platform == platform,
                )
                .first()
            )
            if action is None:
                raise StorageUnavailableError(
                    f"Job action not found: job={job_id}, platform={platform}"
                )
            action.status = status
            action.post_id = post_id
            session.commit()
        except StorageUnavailableError:
            raise
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to update action status: {e}")
        finally:
            session.close()

    def pop_due_jobs(self, now: Optional[datetime] = None) -> List[str]:
        """Pop jobs that are due for dispatch.
        
        Jobs are returned ordered by (scheduled_time, created_seq) for
        deterministic dispatch order.
        
        Args:
            now: Current timestamp (defaults to now)
            
        Returns:
            List of job IDs in dispatch order
        """
        if now is None:
            now = datetime.utcnow()
        
        session = self.SessionLocal()
        try:
            jobs = (
                session.query(JobTable)
                .filter(JobTable.scheduled_time <= now)
                .order_by(JobTable.scheduled_time, JobTable.created_seq)
                .all()
            )
            return [job.id for job in jobs]
        except Exception as e:
            raise StorageUnavailableError(f"Failed to pop due jobs: {e}")
        finally:
            session.close()

    #endregion

    #region Post/Dedup Methods

    def store_post(self, post: Post) -> None:
        """Store published post.
        
        Args:
            post: Post model object
        """
        session = self.SessionLocal()
        try:
            post_table = PostTable(
                id=post.id,
                platform=post.platform,
                platform_post_id=post.platform_post_id,
                content_id=post.content_id,
                account_id=post.account_id,
                published_at=post.published_at,
            )
            session.add(post_table)
            session.commit()
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to store post: {e}")
        finally:
            session.close()

    def lookup_dedup(self, content_id: str, platform: Platform) -> Optional[str]:
        """Lookup existing post for deduplication.
        
        Args:
            content_id: Content identifier
            platform: Platform
            
        Returns:
            Existing post ID or None if not found
        """
        session = self.SessionLocal()
        try:
            dedup = (
                session.query(DedupKeyTable)
                .filter(
                    DedupKeyTable.content_id == content_id,
                    DedupKeyTable.platform == platform,
                )
                .first()
            )
            if dedup is None:
                return None
            return dedup.post_id
        except Exception as e:
            raise StorageUnavailableError(f"Failed to lookup dedup: {e}")
        finally:
            session.close()

    def store_dedup(self, content_id: str, platform: Platform, post_id: str) -> None:
        """Store deduplication key.
        
        Args:
            content_id: Content identifier
            platform: Platform
            post_id: Platform post ID
        """
        session = self.SessionLocal()
        try:
            dedup = DedupKeyTable(
                content_id=content_id,
                platform=platform,
                post_id=post_id,
            )
            session.add(dedup)
            session.commit()
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to store dedup: {e}")
        finally:
            session.close()

    #endregion

    #region Log Methods

    def append_log(self, entry: LogEntry) -> None:
        """Append log entry.
        
        Args:
            entry: Log entry model object
        """
        session = self.SessionLocal()
        try:
            log_entry = LogEntryTable(
                id=entry.id,
                timestamp=entry.timestamp,
                level=entry.level,
                account_id=entry.account_id,
                job_id=entry.job_id,
                outcome=entry.outcome,
                error_code=entry.error_code,
                description=entry.description,
                content_id=entry.content_id,
            )
            session.add(log_entry)
            session.commit()
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to append log: {e}")
        finally:
            session.close()

    def read_logs(self, since: Optional[datetime] = None) -> List[LogEntry]:
        """Read log entries in ascending timestamp order.
        
        Args:
            since: Optional start timestamp
            
        Returns:
            List of log entries ordered by timestamp ascending
        """
        session = self.SessionLocal()
        try:
            query = session.query(LogEntryTable).order_by(LogEntryTable.timestamp.asc())
            if since is not None:
                query = query.filter(LogEntryTable.timestamp >= since)
            logs = query.all()
            return [log.to_model() for log in logs]
        except Exception as e:
            raise StorageUnavailableError(f"Failed to read logs: {e}")
        finally:
            session.close()

    #endregion

    #region Rate Limit Methods

    def load_rate_limit_state(self, platform: Platform) -> RateLimitState:
        """Load rate limit state for platform.
        
        Args:
            platform: Platform
            
        Returns:
            Rate limit state
        """
        session = self.SessionLocal()
        try:
            state = session.query(RateLimitStateTable).filter(
                RateLimitStateTable.platform == platform
            ).first()
            
            if state is None:
                # Initialize with empty state
                state = RateLimitStateTable(
                    platform=platform,
                    request_timestamps=[],
                    paused_until=None,
                )
                session.add(state)
                session.commit()
            
            return state.to_model()
        except Exception as e:
            raise StorageUnavailableError(f"Failed to load rate limit state: {e}")
        finally:
            session.close()

    def save_rate_limit_state(self, state: RateLimitState) -> None:
        """Save rate limit state.
        
        Args:
            state: Rate limit state model object
        """
        session = self.SessionLocal()
        try:
            db_state = session.query(RateLimitStateTable).filter(
                RateLimitStateTable.platform == state.platform
            ).first()
            
            if db_state is None:
                db_state = RateLimitStateTable(
                    platform=state.platform,
                    request_timestamps=[t.isoformat() for t in state.request_timestamps],
                    paused_until=state.paused_until.isoformat() if state.paused_until else None,
                    last_post_time=state.last_post_time.isoformat() if state.last_post_time else None,
                )
                session.add(db_state)
            else:
                db_state.request_timestamps = [t.isoformat() for t in state.request_timestamps]
                db_state.paused_until = state.paused_until.isoformat() if state.paused_until else None
                db_state.last_post_time = state.last_post_time.isoformat() if state.last_post_time else None
            
            session.commit()
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to save rate limit state: {e}")
        finally:
            session.close()

    def last_post_time(self, account_id: str) -> Optional[datetime]:
        """Get last post timestamp for account.
        
        This is used to enforce minimum spacing between posts to same account.
        We look at the most recent post for this account from the posts table.
        
        Args:
            account_id: Account identifier
            
        Returns:
            Last post timestamp or None if no posts
        """
        session = self.SessionLocal()
        try:
            post = (
                session.query(PostTable)
                .filter(PostTable.account_id == account_id)
                .order_by(PostTable.published_at.desc())
                .first()
            )
            if post is None:
                return None
            return post.published_at
        except Exception as e:
            raise StorageUnavailableError(f"Failed to get last post time: {e}")
        finally:
            session.close()

    def update_last_post_time(self, account_id: str, timestamp: datetime) -> None:
        """Record post timestamp for account.
        
        We use the Post table to track this since it already has account_id
        and published_at fields.
        
        Args:
            account_id: Account identifier
            timestamp: Post timestamp
        """
        session = self.SessionLocal()
        try:
            # Create a record that can be queried later
            post = PostTable(
                id=f"post_time_{account_id}_{timestamp.timestamp()}",
                platform=Platform.YOUTUBE,  # Placeholder - not used for rate limiting
                platform_post_id="",
                content_id="",
                account_id=account_id,
                published_at=timestamp,
            )
            session.add(post)
            session.commit()
        except Exception as e:
            session.rollback()
            raise StorageUnavailableError(f"Failed to update last post time: {e}")
        finally:
            session.close()

    #endregion
