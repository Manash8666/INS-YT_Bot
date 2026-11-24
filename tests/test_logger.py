"""Tests for the Logger module."""

from datetime import datetime, timezone

import pytest

from src.youtube_instagram_bot.logger import Logger, LogLevel
from src.youtube_instagram_bot.storage.storage import Storage
from src.youtube_instagram_bot.exceptions import StorageUnavailableError


class TestLoggerVerbosityFiltering:
    """Test verbosity filtering behavior."""

    def test_log_action_filters_by_verbosity(self):
        """Entries below verbosity level are filtered out."""
        # Use in-memory database
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.WARNING)

        # These should be filtered out
        logger.log_action("account1", "job1", "started", level=LogLevel.DEBUG)
        logger.log_action("account1", "job1", "completed", level=LogLevel.INFO)

        # This should be logged
        logger.log_action("account1", "job1", "failed", level=LogLevel.WARNING)
        logger.log_action("account1", "job2", "failed", level=LogLevel.ERROR)

        # Check what was actually written
        logs = storage.read_logs()
        
        # Only WARNING and ERROR entries should be present
        assert len(logs) == 2
        outcomes = [log.outcome for log in logs]
        assert "failed" in outcomes

    def test_log_error_filters_by_verbosity(self):
        """Error entries are filtered by verbosity."""
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.INFO)

        # DEBUG error should be filtered
        logger.log_error("ERR_DEBUG", "Debug error", level=LogLevel.DEBUG)
        
        # INFO and above should be logged
        logger.log_error("ERR_INFO", "Info error", level=LogLevel.INFO)
        logger.log_error("ERR_WARNING", "Warning error", level=LogLevel.WARNING)
        logger.log_error("ERR_ERROR", "Error error", level=LogLevel.ERROR)

        logs = storage.read_logs()
        assert len(logs) == 3
        error_codes = [log.error_code for log in logs]
        assert "ERR_INFO" in error_codes
        assert "ERR_WARNING" in error_codes
        assert "ERR_ERROR" in error_codes


class TestLoggerTimestamps:
    """Test ISO 8601 timestamp format."""

    def test_log_action_has_iso8601_timestamp(self):
        """Log entries have ISO 8601 format timestamps."""
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.INFO)

        before = datetime.now(timezone.utc)
        logger.log_action("account1", "job1", "started")
        after = datetime.now(timezone.utc)

        logs = storage.read_logs()
        assert len(logs) == 1
        
        timestamp = logs[0].timestamp
        # Verify it's a datetime object
        assert isinstance(timestamp, datetime)
        # Verify timestamp is within expected range (naive datetime in test)
        # The logger stores UTC timestamps as naive datetime
        assert before.replace(tzinfo=None) <= timestamp <= after.replace(tzinfo=None)


class TestLoggerStorageIntegration:
    """Test Storage integration."""

    def test_log_entries_preserved_in_storage(self):
        """Log entries are properly persisted to Storage."""
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.DEBUG)

        # Log multiple entries
        logger.log_action("acc1", "job1", "started", level=LogLevel.INFO)
        logger.log_error("ERR1", "Error 1", level=LogLevel.WARNING)
        logger.log_action("acc2", "job2", "completed", level=LogLevel.DEBUG)
        
        # Read back and verify
        logs = storage.read_logs()
        assert len(logs) == 3

    def test_log_entries_ordered_by_timestamp(self):
        """Log entries are stored in ascending timestamp order."""
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.DEBUG)

        # Log entries with small delays
        logger.log_action("acc1", "job1", "started", level=LogLevel.DEBUG)
        logger.log_action("acc2", "job2", "started", level=LogLevel.DEBUG)
        logger.log_action("acc3", "job3", "started", level=LogLevel.DEBUG)

        logs = storage.read_logs()
        assert len(logs) == 3
        
        # Verify ascending order
        timestamps = [log.timestamp for log in logs]
        assert timestamps[0] <= timestamps[1] <= timestamps[2]


class TestLoggerBuffering:
    """Test in-memory buffering when Storage is unavailable."""

    def test_buffer_entries_when_storage_unavailable(self):
        """Entries are buffered when Storage is unavailable."""
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.DEBUG)

        # Override storage to always fail
        def failing_append(entry):
            raise StorageUnavailableError("Storage unavailable")
        
        storage.append_log = failing_append

        # Log entries - they should go to buffer
        logger.log_action("acc1", "job1", "started", level=LogLevel.DEBUG)
        logger.log_action("acc2", "job2", "started", level=LogLevel.DEBUG)

        # Check buffer has entries
        assert len(logger._buffer) == 2

    def test_buffer_fifo_eviction_at_capacity(self):
        """Buffer evicts oldest entries when at capacity."""
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.DEBUG)

        # Override storage to always fail
        def failing_append(entry):
            raise StorageUnavailableError("Storage unavailable")
        
        storage.append_log = failing_append

        # Fill buffer to capacity
        for i in range(10000):
            logger.log_action(f"acc{i}", f"job{i}", "started", level=LogLevel.DEBUG)

        # Buffer should be at max capacity
        assert len(logger._buffer) == 10000

        # Add one more - oldest should be evicted
        logger.log_action("acc10001", "job10001", "started", level=LogLevel.DEBUG)
        
        # Still at capacity, oldest entry gone
        assert len(logger._buffer) == 10000
        # The first account (acc0) should have been evicted
        account_ids = [log.account_id for log in logger._buffer]
        assert "acc0" not in account_ids
        assert "acc10001" in account_ids


class TestLoggerFlush:
    """Test buffer flush when Storage becomes available."""

    def test_flush_writes_buffered_entries(self):
        """Flush writes buffered entries to Storage."""
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.DEBUG)

        # Override storage to fail initially
        call_count = [0]
        
        def failing_then_working_append(entry):
            call_count[0] += 1
            if call_count[0] < 3:
                raise StorageUnavailableError("Storage unavailable")
            # On 3rd call, work normally
            return original_append(entry)
        
        original_append = storage.append_log
        storage.append_log = failing_then_working_append

        # Log entry - goes to buffer
        logger.log_action("acc1", "job1", "started", level=LogLevel.DEBUG)

        # Flush should succeed
        logger.flush(_test_mode=True)

        # Entry should now be in Storage
        logs = storage.read_logs()
        assert len(logs) == 1

    def test_flush_discards_buffer_on_permanent_failure(self):
        """Buffer is discarded if flush fails 10 times."""
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.DEBUG)

        # Override storage to always fail
        def failing_append(entry):
            raise StorageUnavailableError("Storage permanently unavailable")
        
        storage.append_log = failing_append

        # Log entry - goes to buffer
        logger.log_action("acc1", "job1", "started", level=LogLevel.DEBUG)
        assert len(logger._buffer) == 1

        # Flush with limited retries (test mode skips sleep)
        logger.flush(_test_mode=True)

        # Buffer should be discarded
        assert len(logger._buffer) == 0


class TestLogEntryStructure:
    """Test LogEntry field structure."""

    def test_log_action_entry_fields(self):
        """Log action entries have correct fields."""
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.INFO)

        logger.log_action("my_account", "my_job", "started")

        logs = storage.read_logs()
        assert len(logs) == 1
        
        entry = logs[0]
        assert entry.account_id == "my_account"
        assert entry.job_id == "my_job"
        assert entry.outcome == "started"
        assert entry.error_code is None
        assert entry.description is None
        assert entry.content_id is None

    def test_log_error_entry_fields(self):
        """Log error entries have correct fields."""
        storage = Storage("sqlite:///:memory:")
        logger = Logger(storage, verbosity=LogLevel.ERROR)

        logger.log_error("ERR_INVALID", "Invalid content", content_id="content123")

        logs = storage.read_logs()
        assert len(logs) == 1
        
        entry = logs[0]
        assert entry.error_code == "ERR_INVALID"
        assert entry.description == "Invalid content"
        assert entry.content_id == "content123"
        assert entry.account_id is None
        assert entry.job_id is None
        assert entry.outcome is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
