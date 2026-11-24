"""Logger for recording execution events with verbosity filtering."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from ..models.core import LogLevel
from ..models.value_objects import LogEntry
from ..storage.storage import Storage
from ..exceptions import StorageUnavailableError


class Logger:
    """Logger that records execution events with ISO 8601 timestamps.
    
    The Logger filters entries by verbosity level and writes to Storage.
    When Storage is unavailable, entries are buffered in memory with FIFO eviction.
    """

    # Mapping from LogLevel to numeric rank for comparison
    LEVEL_RANK = {
        LogLevel.DEBUG: 10,
        LogLevel.INFO: 20,
        LogLevel.WARNING: 30,
        LogLevel.ERROR: 40,
    }

    def __init__(self, storage: Storage, verbosity: LogLevel = LogLevel.INFO):
        """Initialize the Logger.
        
        Args:
            storage: Storage instance for persisting log entries
            verbosity: Minimum verbosity level to log (default: INFO)
                      Entries below this level are filtered out.
        """
        self.storage = storage
        self.verbosity = verbosity
        # In-memory buffer for when Storage is unavailable
        self._buffer: list[LogEntry] = []
        self._buffer_max_size = 10000

    def _get_level_rank(self, level: LogLevel) -> int:
        """Get numeric rank for a log level.
        
        Args:
            level: LogLevel to rank
            
        Returns:
            Numeric rank (DEBUG=10, INFO=20, WARNING=30, ERROR=40)
        """
        return self.LEVEL_RANK.get(level, 0)

    def _should_log(self, level: LogLevel) -> bool:
        """Check if an entry at this level should be logged.
        
        Args:
            level: LogLevel of the entry
            
        Returns:
            True if level >= configured verbosity
        """
        return self._get_level_rank(level) >= self._get_level_rank(self.verbosity)

    def _write_to_storage(self, entry: LogEntry) -> None:
        """Write a log entry to Storage.
        
        Args:
            entry: LogEntry to write
            
        Raises:
            StorageUnavailableError: If Storage operation fails
        """
        try:
            self.storage.append_log(entry)
        except StorageUnavailableError:
            raise

    def _buffer_entry(self, entry: LogEntry) -> None:
        """Buffer a log entry in memory when Storage is unavailable.
        
        Uses FIFO eviction when buffer is full.
        
        Args:
            entry: LogEntry to buffer
        """
        if len(self._buffer) >= self._buffer_max_size:
            # Remove oldest entry (FIFO)
            self._buffer.pop(0)
        self._buffer.append(entry)

    def log_action(
        self,
        account_id: str,
        job_id: str,
        outcome: str,
        level: LogLevel = LogLevel.INFO,
    ) -> None:
        """Record a platform-action event.
        
        Args:
            account_id: Account identifier
            job_id: Job identifier
            outcome: Event outcome ("started", "completed", or "failed")
            level: Log level (default: INFO)
        """
        if not self._should_log(level):
            return

        timestamp = datetime.now(timezone.utc)
        
        entry = LogEntry(
            id=str(uuid.uuid4()),
            timestamp=timestamp,
            level=level,
            account_id=account_id,
            job_id=job_id,
            outcome=outcome,
            error_code=None,
            description=None,
            content_id=None,
        )
        
        self._attempt_write(entry)

    def log_error(
        self,
        error_code: str,
        description: str,
        content_id: Optional[str] = None,
        level: LogLevel = LogLevel.ERROR,
    ) -> None:
        """Record an error event.
        
        Args:
            error_code: Machine-readable error code
            description: Human-readable error description
            content_id: Affected content identifier (optional)
            level: Log level (default: ERROR)
        """
        if not self._should_log(level):
            return

        timestamp = datetime.now(timezone.utc)
        
        entry = LogEntry(
            id=str(uuid.uuid4()),
            timestamp=timestamp,
            level=level,
            account_id=None,
            job_id=None,
            outcome=None,
            error_code=error_code,
            description=description,
            content_id=content_id,
        )
        
        self._attempt_write(entry)

    def _attempt_write(self, entry: LogEntry) -> None:
        """Attempt to write entry to Storage, buffering on failure.
        
        Args:
            entry: LogEntry to write
        """
        try:
            self._write_to_storage(entry)
        except StorageUnavailableError:
            # Buffer the entry for later
            self._buffer_entry(entry)

    def flush(self, _test_mode: bool = False) -> None:
        """Attempt to write buffered entries to Storage.
        
        Makes up to 10 retry attempts at 30-second intervals.
        If all attempts fail, the buffer is discarded.
        
        Args:
            _test_mode: If True, skip sleep delays (for testing)
        """
        if not self._buffer:
            return

        for attempt in range(10):
            try:
                # Try to write all buffered entries
                for entry in self._buffer:
                    self._write_to_storage(entry)
                # If we get here, all entries were written successfully
                self._buffer.clear()
                return
            except StorageUnavailableError:
                if _test_mode:
                    # In test mode, don't wait between retries
                    continue
                # Wait before retrying (30 seconds)
                import time
                time.sleep(30)

        # All 10 attempts failed - discard remaining buffer
        self._buffer.clear()
