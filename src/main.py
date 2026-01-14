"""
Main entry point for the audio preprocessing service.

Supports multiple processing modes:
- queue: Event-driven via Azure Storage Queue (recommended)
- polling: Periodically scan input container
- manual: API-only, no background processing
"""

import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from .config import settings
from .api import app as api_app
from .queue_listener import queue_listener, polling_listener
from .blob_handler import async_blob_handler

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


# =============================================================================
# Lifecycle Management
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Processing mode: {settings.processing_mode}")
    
    # Start background processing task
    background_task = None
    
    if settings.processing_mode == "queue":
        logger.info("Starting queue listener...")
        background_task = asyncio.create_task(
            queue_listener.run(poll_interval=5)
        )
    elif settings.processing_mode == "polling":
        logger.info("Starting polling listener...")
        background_task = asyncio.create_task(
            polling_listener.run()
        )
    else:
        logger.info("Manual mode - no background processing")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    if background_task:
        queue_listener.stop()
        polling_listener.stop()
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass
    
    await queue_listener.close()
    await async_blob_handler.close()
    
    logger.info("Shutdown complete")


# Apply lifespan to the API app
api_app.router.lifespan_context = lifespan


# =============================================================================
# Signal Handlers
# =============================================================================
def handle_shutdown(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    queue_listener.stop()
    polling_listener.stop()
    sys.exit(0)


# =============================================================================
# Main
# =============================================================================
def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    
    # Log configuration summary
    logger.info("=" * 60)
    logger.info("Audio Preprocessing Service")
    logger.info("=" * 60)
    logger.info(f"Version:         {settings.app_version}")
    logger.info(f"Environment:     {settings.environment}")
    logger.info(f"Processing mode: {settings.processing_mode}")
    logger.info(f"Input:           {settings.azure.container_input}/{settings.azure.folder_input}")
    logger.info(f"Output:          {settings.azure.container_output}/{settings.azure.folder_output}")
    logger.info("-" * 60)
    logger.info(f"VAD:             {'Enabled' if settings.vad.enabled else 'Disabled'}")
    logger.info(f"Noise reduction: {'Enabled' if settings.noise.enabled else 'Disabled'}")
    logger.info(f"Silence compress:{'Enabled' if settings.silence.enabled else 'Disabled'}")
    logger.info(f"Normalization:   {'Enabled' if settings.normalize.enabled else 'Disabled'}")
    logger.info(f"Target format:   {settings.audio.target_sample_rate}Hz, {settings.audio.target_channels}ch, {settings.audio.target_bit_depth}bit")
    logger.info("=" * 60)
    
    # Run the server
    uvicorn.run(
        api_app,
        host=settings.server.host,
        port=settings.server.port,
        workers=settings.server.workers,
        log_level=settings.server.log_level,
        access_log=settings.debug
    )


if __name__ == "__main__":
    main()
