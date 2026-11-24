"""Instagram_Module for Instagram content publishing."""

from typing import Optional

from ..models.core import Platform
from ..storage.storage import Storage
from ..logger import Logger


class Instagram_Module:
    """Instagram module for publishing images and reels."""
    
    def __init__(
        self,
        auth,
        retry,
        rate_limiter,
        storage: Storage,
        logger: Logger,
    ):
        """Initialize Instagram_Module.
        
        Args:
            auth: Auth_Manager for authentication
            retry: Retry_Handler for retry logic
            rate_limiter: Rate_Limiter for rate limiting
            storage: Storage for persistence
            logger: Logger for recording events
        """
        self.auth = auth
        self.retry = retry
        self.rate_limiter = rate_limiter
        self.storage = storage
        self.logger = logger
    
    def publish_image(
        self,
        account_id: str,
        content_id: str,
        caption: Optional[str] = None,
    ) -> str:
        """Publish an Image as a single-image Post.
        
        Args:
            account_id: Account identifier
            content_id: Content to publish
            caption: Optional caption text
            
        Returns:
            Platform post ID
        """
        # Validate caption length
        if caption and len(caption) > 2200:
            from ..exceptions import CaptionTooLongError
            raise CaptionTooLongError(2200)
        
        # Rate limit check
        self.rate_limiter.acquire(Platform.INSTAGRAM, account_id)
        
        # In real implementation, would use Instagram Graph API
        # This is a placeholder that returns a mock post ID
        post_id = f"instagram_{content_id[:8]}_{self._generate_post_id()}"
        
        return post_id
    
    def publish_reel(
        self,
        account_id: str,
        content_id: str,
        caption: Optional[str] = None,
    ) -> str:
        """Publish a Reel with reel media type.
        
        Args:
            account_id: Account identifier
            content_id: Content to publish
            caption: Optional caption text
            
        Returns:
            Platform post ID
        """
        # Validate caption length
        if caption and len(caption) > 2200:
            from ..exceptions import CaptionTooLongError
            raise CaptionTooLongError(2200)
        
        # Rate limit check
        self.rate_limiter.acquire(Platform.INSTAGRAM, account_id)
        
        # In real implementation, would use Instagram Graph API two-phase flow
        # This is a placeholder that returns a mock post ID
        post_id = f"instagram_reel_{content_id[:8]}_{self._generate_post_id()}"
        
        return post_id
    
    def _generate_post_id(self) -> str:
        """Generate a unique post ID.
        
        Returns:
            Post ID string
        """
        import time
        return f"{int(time.time() * 1000)}"
