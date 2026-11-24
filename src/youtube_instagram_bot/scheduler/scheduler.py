"""Fix Scheduler: add missing imports, fix JobStatus/LogLevel usage."""

import heapq
import time
import threading
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import uuid4

from ..models.core import Platform, JobStatus, ActionStatus, LogLevel
from ..models.value_objects import Target, Job, JobAction
from ..storage.storage import Storage
from ..exceptions import StorageUnavailableError


class Scheduler:
    """Priority-queue scheduler with Storage persistence and dispatch retry."""

    def __init__(
        self,
        storage: Storage,
        bot,
        logger,
        check_interval: timedelta = timedelta(seconds=60),
    ):
        self.storage = storage
        self.bot = bot
        self.logger = logger
        self.check_interval = check_interval
        self._heap: List[tuple] = []        # (scheduled_time, created_seq, job_id)
        self._index: dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ── Public API ───────────────────────────────────────────────────────────

    def schedule(
        self,
        job_id: str,
        scheduled_time: datetime,
        targets: List[Target],
        source_content_id: str,
        created_seq: int = 0,
    ) -> None:
        """Persist a Job and add it to the priority queue."""
        actions = [
            JobAction(
                id=str(uuid4()),
                job_id=job_id,
                platform=target.platform,
                account_id=target.account_id,
                content_id=source_content_id,
                status=ActionStatus.PENDING,
                post_id=None,
                dispatch_attempts=0,
                mapping_id=target.mapping_id,
            )
            for target in targets
        ]
        job = Job(
            id=job_id,
            scheduled_time=scheduled_time,
            created_seq=created_seq,
            status=JobStatus.PENDING,
            source_content_id=source_content_id,
            actions=actions,
        )
        self.storage.store_job(job)
        entry = (scheduled_time, created_seq, job_id)
        with self._lock:
            heapq.heappush(self._heap, entry)
            self._index[job_id] = entry

    def start(self) -> None:
        """Start the background check loop in a daemon thread."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self) -> None:
        """Signal the check loop to stop."""
        self._running = False

    # ── Internal ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception as exc:
                self.logger.log_error(
                    error_code="SCHEDULER_TICK_ERROR",
                    description=str(exc),
                )
            time.sleep(self.check_interval.total_seconds())

    def _tick(self) -> None:
        now = datetime.utcnow()
        due_ids = self.storage.pop_due_jobs(now)
        for job_id in due_ids:
            with self._lock:
                self._index.pop(job_id, None)
            self._dispatch(job_id)

    def _dispatch(self, job_id: str) -> None:
        try:
            job = self.storage.load_job(job_id)
        except StorageUnavailableError:
            return

        if job.dispatch_attempts >= 3:
            self.storage.update_job_status(job_id, JobStatus.FAILED)
            self.logger.log_error(
                error_code="JOB_DISPATCH_EXHAUSTED",
                description=f"Job {job_id} failed after 3 dispatch attempts",
            )
            return

        try:
            self.logger.log_action(account_id=None, job_id=job_id, outcome="started")
            self.bot.execute_job(job_id)
            self.logger.log_action(account_id=None, job_id=job_id, outcome="completed")
        except Exception as exc:
            attempt = job.dispatch_attempts + 1
            self.logger.log_error(
                error_code="JOB_DISPATCH_FAILED",
                description=f"Job {job_id} dispatch attempt {attempt}/3: {exc}",
            )
            if attempt < 3:
                # Re-queue for next tick
                entry = (job.scheduled_time, job.created_seq, job_id)
                with self._lock:
                    heapq.heappush(self._heap, entry)
                    self._index[job_id] = entry
            else:
                self.storage.update_job_status(job_id, JobStatus.FAILED)
