"""Bot coordinator for the YouTube-Instagram automation system."""

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from ..models.core import Platform, JobStatus, ActionStatus, LogLevel
from ..models.value_objects import Target, Job, JobAction
from ..storage.storage import Storage
from ..logger import Logger
from ..exceptions import UnsupportedFormatError


class Bot:
    """Bot coordinator that manages cross-platform publishing.
    
    Coordinates Auth_Manager, Content_Manager, YouTube_Module, Instagram_Module,
    Scheduler, Rate_Limiter, Retry_Handler, and Logger.
    """
    
    def __init__(
        self,
        auth,
        content,
        youtube,
        instagram,
        scheduler,
        rate_limiter,
        retry,
        logger: Logger,
        storage: Storage,
    ):
        """Initialize Bot coordinator.
        
        Args:
            auth: Auth_Manager for authentication
            content: Content_Manager for content ingestion/storage
            youtube: YouTube_Module for YouTube publishing
            instagram: Instagram_Module for Instagram publishing
            scheduler: Scheduler for job queueing
            rate_limiter: Rate_Limiter for rate limiting
            retry: Retry_Handler for retry logic
            logger: Logger for recording events
            storage: Storage for persistence
        """
        self.auth = auth
        self.content = content
        self.youtube = youtube
        self.instagram = instagram
        self.scheduler = scheduler
        self.rate_limiter = rate_limiter
        self.retry = retry
        self.logger = logger
        self.storage = storage
    
    def create_job(
        self,
        content_id: str,
        targets: List[Target],
        scheduled_time: Optional[datetime] = None,
    ) -> str:
        """Create and enqueue a Job.
        
        Args:
            content_id: Content asset identifier
            targets: List of target platforms with account IDs
            scheduled_time: Optional scheduled time (None = immediate dispatch)
            
        Returns:
            Job identifier
        """
        job_id = str(uuid4())
        created_seq = 0  # Will be populated by scheduler
        
        # If no scheduled time, dispatch immediately
        if scheduled_time is None:
            # Create job directly without scheduler
            self._execute_job_direct(job_id, content_id, targets)
        else:
            # Queue for scheduler
            self.scheduler.schedule(job_id, scheduled_time, targets, content_id, created_seq)
        
        return job_id
    
    def _execute_job_direct(
        self,
        job_id: str,
        content_id: str,
        targets: List[Target],
    ) -> None:
        """Execute job immediately without scheduling.
        
        Args:
            job_id: Job identifier
            content_id: Content asset identifier
            targets: List of target platforms with account IDs
        """
        # Create job record
        actions = []
        for target in targets:
            action = JobAction(
                id=str(uuid4()),
                job_id=job_id,
                platform=target.platform,
                account_id=target.account_id,
                content_id=content_id,
                status=ActionStatus.PENDING,
                post_id=None,
                dispatch_attempts=0,
                mapping_id=target.mapping_id,
            )
            actions.append(action)
        
        job = Job(
            id=job_id,
            scheduled_time=datetime.utcnow(),
            created_seq=0,
            status=JobStatus.PENDING,
            source_content_id=content_id,
            actions=actions,
        )
        
        # Log job start
        self.logger.log_action(
            account_id=None,
            job_id=job_id,
            outcome="started",
            level=LogLevel.INFO,
        )
        
        # Execute actions
        self._execute_actions(job)
    
    def execute_job(self, job_id: str) -> JobStatus:
        """Execute all platform actions for a Job with idempotency.
        
        Args:
            job_id: Job identifier
            
        Returns:
            JobStatus (complete, partially_complete, or failed)
        """
        job = self.storage.load_job(job_id)
        return self._execute_actions(job)
    
    def _execute_actions(self, job: Job) -> JobStatus:
        """Execute all platform actions for a Job.
        
        Args:
            job: Job to execute
            
        Returns:
            JobStatus (complete, partially_complete, or failed)
        """
        actions = job.actions
        successful_count = 0
        failed_count = 0
        partially_complete = False
        
        for action in actions:
            # Log action start
            self.logger.log_action(
                account_id=action.account_id,
                job_id=job.id,
                outcome="started",
                level=LogLevel.INFO,
            )
            
            try:
                # Check idempotency first
                existing_post = self.storage.lookup_dedup(
                    action.content_id, action.platform
                )
                if existing_post is not None:
                    self.storage.update_action_status(
                        job.id, action.platform, ActionStatus.SUCCEEDED, existing_post
                    )
                    successful_count += 1
                    self.logger.log_action(
                        account_id=action.account_id,
                        job_id=job.id,
                        outcome="completed",
                        level=LogLevel.INFO,
                    )
                    continue
                
                # Apply cross-posting mapping if configured
                if action.mapping_id is not None:
                    try:
                        # In real implementation, would call content.apply_mapping
                        pass
                    except UnsupportedFormatError as e:
                        self.logger.log_error(
                            error_code="MAPPING_FAILED",
                            description=f"Mapping {action.mapping_id} failed: {e}",
                            content_id=action.content_id,
                        )
                        self.storage.update_action_status(
                            job.id, action.platform, ActionStatus.FAILED, None
                        )
                        failed_count += 1
                        partially_complete = True
                        continue
                
                # Publish based on platform
                if action.platform == Platform.YOUTUBE:
                    post_id = self._publish_youtube(action)
                elif action.platform == Platform.INSTAGRAM:
                    post_id = self._publish_instagram(action)
                else:
                    raise ValueError(f"Unknown platform: {action.platform}")
                
                # Store deduplication key on success
                self.storage.store_dedup(action.content_id, action.platform, post_id)
                self.storage.update_action_status(
                    job.id, action.platform, ActionStatus.SUCCEEDED, post_id
                )
                successful_count += 1
                
            except Exception as e:
                self.storage.update_action_status(
                    job.id, action.platform, ActionStatus.FAILED, None
                )
                failed_count += 1
                partially_complete = True
                self.logger.log_error(
                    error_code="PUBLISH_FAILED",
                    description=f"Publish to {action.platform.value} failed: {e}",
                    content_id=action.content_id,
                )
            
            self.logger.log_action(
                account_id=action.account_id,
                job_id=job.id,
                outcome="completed",
                level=LogLevel.INFO,
            )
        
        # Aggregate final status
        if failed_count == 0:
            final_status = JobStatus.COMPLETE
        elif successful_count == 0:
            final_status = JobStatus.FAILED
        else:
            final_status = JobStatus.PARTIALLY_COMPLETE
        
        # Update job status
        self.storage.update_job_status(job.id, final_status)
        
        return final_status
    
    def _publish_youtube(self, action: JobAction) -> str:
        """Publish to YouTube.
        
        Args:
            action: Job action
            
        Returns:
            Platform post ID
        """
        return self.youtube.upload_video(
            account_id=action.account_id,
            content_id=action.content_id,
            vertical=True,  # Shorts format
        )
    
    def _publish_instagram(self, action: JobAction) -> str:
        """Publish to Instagram.
        
        Args:
            action: Job action
            
        Returns:
            Platform post ID
        """
        return self.instagram.publish_reel(
            account_id=action.account_id,
            content_id=action.content_id,
        )
