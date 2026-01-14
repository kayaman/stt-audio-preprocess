"""
Queue-based event processing for audio files.

Supports:
- Azure Storage Queue (for Event Grid blob events)
- Polling mode (fallback)
"""

import asyncio
import json
import logging
import base64
from typing import Optional, Callable, Any
from datetime import datetime, timezone
from dataclasses import dataclass

from azure.storage.queue import QueueClient
from azure.storage.queue.aio import QueueClient as AsyncQueueClient
from azure.identity import DefaultAzureCredential

from .config import settings
from .blob_handler import blob_handler, BlobInfo
from .audio_processor import processor, ProcessingStats

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a single file."""
    success: bool
    input_path: str
    output_path: Optional[str] = None
    stats: Optional[ProcessingStats] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0


class AudioProcessingWorker:
    """Worker that processes audio files."""
    
    def __init__(self):
        self.processed_count = 0
        self.error_count = 0
    
    def process_blob(self, blob_info: BlobInfo) -> ProcessingResult:
        """Process a single blob."""
        import time
        start_time = time.time()
        
        input_path = blob_info.full_path
        logger.info(f"Processing: {input_path}")
        
        try:
            # Download
            audio_data = blob_handler.download_blob(
                blob_info.container,
                blob_info.name
            )
            
            # Process
            processed_data, stats = processor.process(audio_data, blob_info.filename)
            
            # Build output path
            output_folder = settings.azure.folder_output.rstrip("/") + "/" if settings.azure.folder_output else ""
            output_name = f"{output_folder}{blob_info.stem}.wav"
            
            # Upload
            output_path = blob_handler.upload_blob(
                settings.azure.container_output,
                output_name,
                processed_data,
                content_type="audio/wav"
            )
            
            # Delete source if configured
            if settings.azure.delete_source:
                blob_handler.delete_blob(blob_info.container, blob_info.name)
                logger.info(f"Deleted source: {input_path}")
            
            self.processed_count += 1
            duration = time.time() - start_time
            
            logger.info(f"Completed: {input_path} → {output_path} ({duration:.2f}s)")
            
            return ProcessingResult(
                success=True,
                input_path=input_path,
                output_path=output_path,
                stats=stats,
                duration_seconds=duration
            )
            
        except Exception as e:
            self.error_count += 1
            duration = time.time() - start_time
            logger.error(f"Failed: {input_path} - {e}")
            
            return ProcessingResult(
                success=False,
                input_path=input_path,
                error=str(e),
                duration_seconds=duration
            )


class QueueListener:
    """
    Listen to Azure Storage Queue for blob events.
    
    Expected message format (from Event Grid):
    {
        "eventType": "Microsoft.Storage.BlobCreated",
        "subject": "/blobServices/default/containers/{container}/blobs/{blob}",
        "data": {
            "url": "https://...",
            "contentLength": 12345
        }
    }
    """
    
    def __init__(self):
        self._queue_client: Optional[AsyncQueueClient] = None
        self._worker = AudioProcessingWorker()
        self._running = False
    
    async def _get_queue_client(self) -> AsyncQueueClient:
        """Get or create async queue client."""
        if self._queue_client is None:
            if settings.azure.storage_connection_string:
                self._queue_client = AsyncQueueClient.from_connection_string(
                    settings.azure.storage_connection_string,
                    settings.azure.queue_name
                )
            elif settings.azure.storage_account_name:
                credential = DefaultAzureCredential()
                self._queue_client = AsyncQueueClient(
                    account_url=f"https://{settings.azure.storage_account_name}.queue.core.windows.net",
                    queue_name=settings.azure.queue_name,
                    credential=credential
                )
            else:
                raise ValueError("No Azure Storage credentials configured")
        return self._queue_client
    
    def _parse_message(self, message_content: str) -> Optional[BlobInfo]:
        """Parse queue message and extract blob info."""
        try:
            # Messages might be base64 encoded
            try:
                decoded = base64.b64decode(message_content).decode('utf-8')
            except Exception:
                decoded = message_content
            
            data = json.loads(decoded)
            
            # Handle Event Grid format
            if "eventType" in data:
                if data["eventType"] != "Microsoft.Storage.BlobCreated":
                    return None
                
                # Parse subject: /blobServices/default/containers/{container}/blobs/{blob}
                subject = data.get("subject", "")
                parts = subject.split("/containers/", 1)
                if len(parts) != 2:
                    return None
                
                container_and_blob = parts[1].split("/blobs/", 1)
                if len(container_and_blob) != 2:
                    return None
                
                container = container_and_blob[0]
                blob_name = container_and_blob[1]
                
                # Check if it's in our input container/folder
                if container != settings.azure.container_input:
                    return None
                
                if settings.azure.folder_input and not blob_name.startswith(settings.azure.folder_input):
                    return None
                
                # Check extension
                ext = f".{blob_name.rsplit('.', 1)[-1].lower()}" if "." in blob_name else ""
                if ext not in settings.audio.supported_extensions:
                    return None
                
                return BlobInfo(
                    name=blob_name,
                    container=container,
                    size=data.get("data", {}).get("contentLength", 0),
                    content_type=data.get("data", {}).get("contentType"),
                    last_modified=None
                )
            
            # Handle simple format: {"container": "...", "blob": "..."}
            if "container" in data and "blob" in data:
                return BlobInfo(
                    name=data["blob"],
                    container=data["container"],
                    size=data.get("size", 0),
                    content_type=data.get("content_type"),
                    last_modified=None
                )
            
            return None
            
        except Exception as e:
            logger.warning(f"Failed to parse message: {e}")
            return None
    
    async def process_messages(self, max_messages: int = 10):
        """Process a batch of messages from the queue."""
        client = await self._get_queue_client()
        
        messages = await client.receive_messages(
            max_messages=max_messages,
            visibility_timeout=300  # 5 minutes to process
        )
        
        processed = 0
        async for message in messages:
            blob_info = self._parse_message(message.content)
            
            if blob_info:
                # Run processing in thread pool (CPU-bound)
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    self._worker.process_blob,
                    blob_info
                )
                
                if result.success:
                    await client.delete_message(message)
                    processed += 1
                else:
                    # Message will become visible again after timeout
                    logger.warning(f"Processing failed, message will retry: {result.error}")
            else:
                # Invalid message, delete it
                await client.delete_message(message)
        
        return processed
    
    async def run(self, poll_interval: int = 5):
        """Run the queue listener continuously."""
        self._running = True
        logger.info(f"Queue listener started, polling every {poll_interval}s")
        
        while self._running:
            try:
                processed = await self.process_messages()
                if processed > 0:
                    logger.info(f"Processed {processed} messages")
            except Exception as e:
                logger.error(f"Error processing messages: {e}")
            
            await asyncio.sleep(poll_interval)
    
    def stop(self):
        """Stop the queue listener."""
        self._running = False
        logger.info("Queue listener stopping...")
    
    async def close(self):
        """Close connections."""
        if self._queue_client:
            await self._queue_client.close()
            self._queue_client = None


class PollingListener:
    """
    Polling-based listener that scans the input container for new files.
    
    Less efficient than queue-based, but works without Event Grid setup.
    """
    
    def __init__(self):
        self._worker = AudioProcessingWorker()
        self._running = False
        self._processed_blobs: set = set()  # Track processed to avoid duplicates
    
    async def scan_and_process(self) -> int:
        """Scan for new blobs and process them."""
        # List blobs in input container
        blobs = blob_handler.list_blobs(
            settings.azure.container_input,
            prefix=settings.azure.folder_input,
            extensions=settings.audio.supported_extensions
        )
        
        processed = 0
        loop = asyncio.get_event_loop()
        
        for blob_info in blobs:
            # Skip already processed
            if blob_info.full_path in self._processed_blobs:
                continue
            
            # Process in thread pool
            result = await loop.run_in_executor(
                None,
                self._worker.process_blob,
                blob_info
            )
            
            if result.success:
                self._processed_blobs.add(blob_info.full_path)
                processed += 1
            
            # Clean up processed set periodically
            if len(self._processed_blobs) > 10000:
                self._processed_blobs.clear()
        
        return processed
    
    async def run(self, poll_interval: Optional[int] = None):
        """Run the polling listener continuously."""
        interval = poll_interval or settings.polling_interval_seconds
        self._running = True
        logger.info(f"Polling listener started, interval: {interval}s")
        
        while self._running:
            try:
                processed = await self.scan_and_process()
                if processed > 0:
                    logger.info(f"Processed {processed} files")
            except Exception as e:
                logger.error(f"Error during polling: {e}")
            
            await asyncio.sleep(interval)
    
    def stop(self):
        """Stop the polling listener."""
        self._running = False
        logger.info("Polling listener stopping...")


# Global instances
queue_listener = QueueListener()
polling_listener = PollingListener()
worker = AudioProcessingWorker()
