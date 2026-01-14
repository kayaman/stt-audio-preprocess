"""
Azure Blob Storage operations for audio processing.
"""

import logging
from typing import Optional, List, AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone

from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.storage.blob.aio import BlobServiceClient as AsyncBlobServiceClient
from azure.identity import DefaultAzureCredential

from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class BlobInfo:
    """Information about a blob."""
    name: str
    container: str
    size: int
    content_type: Optional[str]
    last_modified: Optional[datetime]
    
    @property
    def full_path(self) -> str:
        return f"{self.container}/{self.name}"
    
    @property
    def filename(self) -> str:
        return self.name.rsplit("/", 1)[-1] if "/" in self.name else self.name
    
    @property
    def stem(self) -> str:
        filename = self.filename
        return filename.rsplit(".", 1)[0] if "." in filename else filename
    
    @property
    def extension(self) -> str:
        filename = self.filename
        return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


class BlobHandler:
    """Synchronous blob storage handler."""
    
    def __init__(self):
        self._client: Optional[BlobServiceClient] = None
    
    @property
    def client(self) -> BlobServiceClient:
        """Lazy initialization of blob service client."""
        if self._client is None:
            if settings.azure.storage_connection_string:
                self._client = BlobServiceClient.from_connection_string(
                    settings.azure.storage_connection_string
                )
                logger.info("BlobServiceClient initialized with connection string")
            elif settings.azure.storage_account_name:
                credential = DefaultAzureCredential()
                self._client = BlobServiceClient(
                    account_url=f"https://{settings.azure.storage_account_name}.blob.core.windows.net",
                    credential=credential
                )
                logger.info("BlobServiceClient initialized with managed identity")
            else:
                raise ValueError("No Azure Storage credentials configured")
        return self._client
    
    def download_blob(self, container: str, blob_name: str) -> bytes:
        """Download blob content as bytes."""
        blob_client = self.client.get_blob_client(container, blob_name)
        return blob_client.download_blob().readall()
    
    def upload_blob(
        self,
        container: str,
        blob_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        overwrite: bool = True
    ) -> str:
        """Upload data to blob storage."""
        blob_client = self.client.get_blob_client(container, blob_name)
        blob_client.upload_blob(
            data,
            overwrite=overwrite,
            content_settings=ContentSettings(content_type=content_type)
        )
        return f"{container}/{blob_name}"
    
    def delete_blob(self, container: str, blob_name: str) -> bool:
        """Delete a blob."""
        try:
            blob_client = self.client.get_blob_client(container, blob_name)
            blob_client.delete_blob()
            return True
        except Exception as e:
            logger.warning(f"Failed to delete blob {container}/{blob_name}: {e}")
            return False
    
    def list_blobs(
        self,
        container: str,
        prefix: Optional[str] = None,
        extensions: Optional[tuple] = None
    ) -> List[BlobInfo]:
        """List blobs in a container with optional filtering."""
        container_client = self.client.get_container_client(container)
        blobs = []
        
        for blob in container_client.list_blobs(name_starts_with=prefix):
            if extensions:
                ext = f".{blob.name.rsplit('.', 1)[-1].lower()}" if "." in blob.name else ""
                if ext not in extensions:
                    continue
            
            blobs.append(BlobInfo(
                name=blob.name,
                container=container,
                size=blob.size,
                content_type=blob.content_settings.content_type if blob.content_settings else None,
                last_modified=blob.last_modified
            ))
        
        return blobs
    
    def blob_exists(self, container: str, blob_name: str) -> bool:
        """Check if a blob exists."""
        blob_client = self.client.get_blob_client(container, blob_name)
        return blob_client.exists()
    
    def get_blob_info(self, container: str, blob_name: str) -> Optional[BlobInfo]:
        """Get information about a specific blob."""
        blob_client = self.client.get_blob_client(container, blob_name)
        try:
            props = blob_client.get_blob_properties()
            return BlobInfo(
                name=blob_name,
                container=container,
                size=props.size,
                content_type=props.content_settings.content_type if props.content_settings else None,
                last_modified=props.last_modified
            )
        except Exception:
            return None


class AsyncBlobHandler:
    """Asynchronous blob storage handler for high-throughput scenarios."""
    
    def __init__(self):
        self._client: Optional[AsyncBlobServiceClient] = None
    
    async def _get_client(self) -> AsyncBlobServiceClient:
        """Get or create async blob service client."""
        if self._client is None:
            if settings.azure.storage_connection_string:
                self._client = AsyncBlobServiceClient.from_connection_string(
                    settings.azure.storage_connection_string
                )
            elif settings.azure.storage_account_name:
                credential = DefaultAzureCredential()
                self._client = AsyncBlobServiceClient(
                    account_url=f"https://{settings.azure.storage_account_name}.blob.core.windows.net",
                    credential=credential
                )
            else:
                raise ValueError("No Azure Storage credentials configured")
        return self._client
    
    async def download_blob(self, container: str, blob_name: str) -> bytes:
        """Download blob content as bytes."""
        client = await self._get_client()
        blob_client = client.get_blob_client(container, blob_name)
        stream = await blob_client.download_blob()
        return await stream.readall()
    
    async def upload_blob(
        self,
        container: str,
        blob_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        overwrite: bool = True
    ) -> str:
        """Upload data to blob storage."""
        client = await self._get_client()
        blob_client = client.get_blob_client(container, blob_name)
        await blob_client.upload_blob(
            data,
            overwrite=overwrite,
            content_settings=ContentSettings(content_type=content_type)
        )
        return f"{container}/{blob_name}"
    
    async def delete_blob(self, container: str, blob_name: str) -> bool:
        """Delete a blob."""
        try:
            client = await self._get_client()
            blob_client = client.get_blob_client(container, blob_name)
            await blob_client.delete_blob()
            return True
        except Exception as e:
            logger.warning(f"Failed to delete blob {container}/{blob_name}: {e}")
            return False
    
    async def list_blobs(
        self,
        container: str,
        prefix: Optional[str] = None,
        extensions: Optional[tuple] = None
    ) -> List[BlobInfo]:
        """List blobs in a container."""
        client = await self._get_client()
        container_client = client.get_container_client(container)
        blobs = []
        
        async for blob in container_client.list_blobs(name_starts_with=prefix):
            if extensions:
                ext = f".{blob.name.rsplit('.', 1)[-1].lower()}" if "." in blob.name else ""
                if ext not in extensions:
                    continue
            
            blobs.append(BlobInfo(
                name=blob.name,
                container=container,
                size=blob.size,
                content_type=blob.content_settings.content_type if blob.content_settings else None,
                last_modified=blob.last_modified
            ))
        
        return blobs
    
    async def close(self):
        """Close the client connection."""
        if self._client:
            await self._client.close()
            self._client = None


# Global handler instances
blob_handler = BlobHandler()
async_blob_handler = AsyncBlobHandler()
