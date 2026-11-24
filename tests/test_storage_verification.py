"""Verification test for Storage persistence layer round-trips."""

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Set up environment before importing bot modules
os.environ['BOT_MASTER_KEY'] = 'test-master-key-for-verification'

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from youtube_instagram_bot.storage.storage import Storage
from youtube_instagram_bot.models.core import Platform, ContentType, AccountStatus, JobStatus, ActionStatus, LogLevel
from youtube_instagram_bot.models.value_objects import Account, Content, Job, JobAction, Post, DedupKey, LogEntry, RateLimitState


def test_content_roundtrip():
    """Verify content bytes are byte-identical after storage round-trip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        storage = Storage(f"sqlite:///{db_path}")
        
        # Test with various content types
        test_cases = [
            (b"simple text content", "text/plain"),
            (b"\x00\x01\x02\x03\xff\xfe\xfd", "application/octet-stream"),
            (b"large content " * 1000, "text/large"),
        ]
        
        for blob, fmt in test_cases:
            content_id = f"content_{id(blob)}"
            storage.store_content(
                content_id=content_id,
                content_type=ContentType.TEXT,
                fmt=fmt,
                blob=blob,
                metadata={"test": True}
            )
            
            # Verify round-trip
            read_bytes = storage.read_content(content_id)
            assert read_bytes == blob, f"Bytes mismatch for {fmt}"
            
            # Verify metadata
            metadata = storage.read_metadata(content_id)
            assert metadata == {"test": True}
        
        print("✓ Content round-trip test passed")


def test_account_persistence():
    """Verify account storage and updates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        storage = Storage(f"sqlite:///{db_path}")
        
        account_id = "test_account_1"
        platform = Platform.YOUTUBE
        encrypted_creds = b"encrypted_credentials_blob"
        encrypted_token = b"encrypted_access_token"
        encrypted_refresh = b"encrypted_refresh_token"
        expires_at = datetime.utcnow() + timedelta(hours=1)
        
        # Store account
        storage.store_account(
            account_id=account_id,
            platform=platform,
            status=AccountStatus.AUTHORIZED,
            encrypted_creds=encrypted_creds,
            encrypted_access_token=encrypted_token,
            encrypted_refresh_token=encrypted_refresh,
            token_expires_at=expires_at
        )
        
        # Load account
        account = storage.load_account(account_id)
        assert account.id == account_id
        assert account.platform == platform
        assert account.status == AccountStatus.AUTHORIZED
        assert account.encrypted_credentials == encrypted_creds
        
        # Test load_encrypted_creds
        creds = storage.load_encrypted_creds(account_id)
        assert creds == encrypted_creds
        
        # Update status
        storage.update_account_status(account_id, AccountStatus.UNAUTHORIZED)
        account = storage.load_account(account_id)
        assert account.status == AccountStatus.UNAUTHORIZED
        
        # Store new token
        new_token = b"new_encrypted_token"
        storage.store_encrypted_token(account_id, new_token)
        account = storage.load_account(account_id)
        assert account.encrypted_access_token == new_token
        
        print("✓ Account persistence test passed")


def test_job_persistence():
    """Verify job serialization/deserialization preserves scheduled_time and targets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        storage = Storage(f"sqlite:///{db_path}")
        
        scheduled_time = datetime.utcnow() + timedelta(hours=1)
        job = Job(
            id="test_job_1",
            scheduled_time=scheduled_time,
            created_seq=42,
            status=JobStatus.PENDING,
            source_content_id="content_123",
            actions=[
                JobAction(
                    id="action_1",
                    job_id="test_job_1",
                    platform=Platform.YOUTUBE,
                    account_id="yt_account_1",
                    content_id="content_123",
                    status=ActionStatus.PENDING,
                    post_id=None,
                    dispatch_attempts=0,
                    mapping_id=None
                ),
                JobAction(
                    id="action_2",
                    job_id="test_job_1",
                    platform=Platform.INSTAGRAM,
                    account_id="ig_account_1",
                    content_id="content_123",
                    status=ActionStatus.PENDING,
                    post_id=None,
                    dispatch_attempts=0,
                    mapping_id=None
                )
            ]
        )
        
        # Store job
        storage.store_job(job)
        
        # Load and verify
        loaded_job = storage.load_job("test_job_1")
        assert loaded_job.id == job.id
        assert loaded_job.scheduled_time == job.scheduled_time
        assert loaded_job.created_seq == job.created_seq
        assert len(loaded_job.actions) == 2
        
        # Verify actions
        action_map = {a.platform: a for a in loaded_job.actions}
        assert Platform.YOUTUBE in action_map
        assert Platform.INSTAGRAM in action_map
        
        print("✓ Job persistence test passed")


def test_pop_due_jobs_ordering():
    """Verify pop_due_jobs returns jobs ordered by (scheduled_time, created_seq)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        storage = Storage(f"sqlite:///{db_path}")
        
        now = datetime.utcnow()
        
        # Create jobs with various scheduled times
        jobs_data = [
            ("job_3", now + timedelta(seconds=3), 3),
            ("job_1", now + timedelta(seconds=1), 1),
            ("job_2", now + timedelta(seconds=1), 2),  # Same time, higher seq
            ("job_future", now + timedelta(seconds=10), 0),
        ]
        
        for job_id, sched_time, seq in jobs_data:
            job = Job(
                id=job_id,
                scheduled_time=sched_time,
                created_seq=seq,
                status=JobStatus.PENDING,
                source_content_id="content_123",
                actions=[]
            )
            storage.store_job(job)
        
        # Pop due jobs (only jobs at or before now + 3 seconds)
        due = storage.pop_due_jobs(now + timedelta(seconds=3))
        
        # Should be in order: job_1 (seq 1), job_2 (seq 2), job_3 (seq 3)
        assert due == ["job_1", "job_2", "job_3"], f"Expected ordered job IDs, got {due}"
        
        # job_future should not be included
        assert "job_future" not in due
        
        print("✓ pop_due_jobs ordering test passed")


def test_post_and_dedup():
    """Verify post storage and deduplication lookup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        storage = Storage(f"sqlite:///{db_path}")
        
        # Store a post
        post = Post(
            id="post_1",
            platform=Platform.YOUTUBE,
            platform_post_id="yt_video_abc123",
            content_id="content_123",
            account_id="yt_account_1",
            published_at=datetime.utcnow()
        )
        storage.store_post(post)
        
        # Store dedup key
        storage.store_dedup("content_123", Platform.YOUTUBE, "yt_video_abc123")
        
        # Lookup dedup
        existing = storage.lookup_dedup("content_123", Platform.YOUTUBE)
        assert existing == "yt_video_abc123"
        
        # Non-existent lookup
        none_result = storage.lookup_dedup("content_nonexistent", Platform.YOUTUBE)
        assert none_result is None
        
        print("✓ Post and dedup test passed")


def test_log_persistence():
    """Verify log entries are returned in ascending timestamp order."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        storage = Storage(f"sqlite:///{db_path}")
        
        base_time = datetime.utcnow()
        
        # Create logs with timestamps in non-sequential order
        logs = [
            LogEntry(
                id=f"log_{i}",
                timestamp=base_time + timedelta(seconds=i * 10),
                level=LogLevel.INFO,
                account_id=f"account_{i}",
                job_id=f"job_{i}",
                outcome="completed",
                error_code=None,
                description=None,
                content_id=f"content_{i}"
            )
            for i in range(5)
        ]
        
        # Append in reverse order
        for log in reversed(logs):
            storage.append_log(log)
        
        # Read all logs
        all_logs = storage.read_logs()
        assert len(all_logs) == 5
        
        # Verify ascending timestamp order
        for i in range(len(all_logs) - 1):
            assert all_logs[i].timestamp <= all_logs[i + 1].timestamp, "Logs not in ascending order"
        
        # Verify timestamps match what we stored
        stored_timestamps = [log.timestamp for log in logs]
        read_timestamps = [log.timestamp for log in all_logs]
        assert sorted(stored_timestamps) == read_timestamps
        
        print("✓ Log persistence test passed")


def test_rate_limit_state():
    """Verify rate limit state persistence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        storage = Storage(f"sqlite:///{db_path}")
        
        # Load initial state (should create default)
        state = storage.load_rate_limit_state(Platform.YOUTUBE)
        assert state.platform == Platform.YOUTUBE
        assert state.request_timestamps == []
        assert state.paused_until is None
        
        # Save state with timestamps
        now = datetime.utcnow()
        state.request_timestamps = [now - timedelta(seconds=5), now - timedelta(seconds=2)]
        state.paused_until = now + timedelta(minutes=5)
        storage.save_rate_limit_state(state)
        
        # Load and verify
        loaded = storage.load_rate_limit_state(Platform.YOUTUBE)
        assert len(loaded.request_timestamps) == 2
        assert loaded.paused_until is not None
        
        print("✓ Rate limit state test passed")


def test_last_post_time():
    """Verify last post time tracking."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        storage = Storage(f"sqlite:///{db_path}")
        
        account_id = "yt_account_1"
        
        # No posts yet
        last = storage.last_post_time(account_id)
        assert last is None
        
        # Record post times
        time1 = datetime.utcnow() - timedelta(hours=2)
        storage.update_last_post_time(account_id, time1)
        
        time2 = datetime.utcnow() - timedelta(hours=1)
        storage.update_last_post_time(account_id, time2)
        
        # Should return most recent
        last = storage.last_post_time(account_id)
        assert last == time2
        
        print("✓ Last post time test passed")


if __name__ == "__main__":
    print("Running Storage verification tests...\n")
    
    test_content_roundtrip()
    test_account_persistence()
    test_job_persistence()
    test_pop_due_jobs_ordering()
    test_post_and_dedup()
    test_log_persistence()
    test_rate_limit_state()
    test_last_post_time()
    
    print("\n✓ All Storage verification tests passed!")
