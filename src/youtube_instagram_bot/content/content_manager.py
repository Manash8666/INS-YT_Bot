"""Content_Manager for content ingestion, storage, and format conversion."""

from typing import Optional
from uuid import uuid4

from ..models.core import ContentType
from ..models.value_objects import Content as ContentModel
from ..storage.storage import Storage
from ..exceptions import UnsupportedFormatError


SUPPORTED_FORMATS = {
    ContentType.IMAGE: {"jpeg", "jpg", "png"},
    ContentType.VIDEO: {"mp4"},
    ContentType.TEXT: {"txt", "plain"},
}


class Content_Manager:
    """Manages content ingestion, storage, and format conversion.
    
    Validates formats against supported formats, stores content with
    unique identifiers, and returns byte-identical content on read.
    """
    
    def __init__(self, storage: Storage):
        """Initialize Content_Manager.
        
        Args:
            storage: Storage layer for persisting content
        """
        self.storage = storage
    
    def ingest(
        self,
        asset: bytes,
        content_type: ContentType,
        fmt: str,
        metadata: Optional[dict] = None,
    ) -> str:
        """Ingest and store content asset.
        
        Validates format against SUPPORTED_FORMATS. If format is not
        supported, raises UnsupportedFormatError without storing the asset.
        Otherwise, stores the asset and metadata, assigns a unique content_id,
        and returns it.
        
        Args:
            asset: Raw bytes of the content asset
            content_type: Type of content (image, video, text)
            fmt: File format (e.g., "jpeg", "png", "mp4", "txt")
            metadata: Optional metadata dictionary
            
        Returns:
            Unique content_id string
            
        Raises:
            UnsupportedFormatError: If fmt is not supported for content_type
        """
        # Validate format against supported formats
        if fmt.lower() not in SUPPORTED_FORMATS[content_type]:
            raise UnsupportedFormatError(
                f"Format '{fmt}' is not supported for content type '{content_type.name}'"
            )
        
        # Generate unique content_id
        content_id = str(uuid4())
        
        # Store content with metadata
        self.storage.store_content(
            content_id=content_id,
            content_type=content_type,
            fmt=fmt,
            blob=asset,
            metadata=metadata or {},
        )
        
        return content_id
    
    def read(self, content_id: str) -> bytes:
        """Read content bytes.
        
        Returns bytes that are byte-identical to the originally ingested bytes.
        
        Args:
            content_id: Unique content identifier
            
        Returns:
            Raw bytes of the content
            
        Raises:
            StorageUnavailableError: If content not found or database error
        """
        return self.storage.read_content(content_id)
    
    def get_metadata(self, content_id: str) -> dict:
        """Read content metadata.
        
        Args:
            content_id: Unique content identifier
            
        Returns:
            Metadata dictionary
            
        Raises:
            StorageUnavailableError: If content not found or database error
        """
        return self.storage.read_metadata(content_id)
