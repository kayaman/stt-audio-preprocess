"""
Main entry point for the audio preprocessing service.
"""

import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from .config import settings
from .api import app as api_app

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
    
    yield
    
    logger.info("Shutdown complete")


# Apply lifespan to the API app
api_app.router.lifespan_context = lifespan


# =============================================================================
# Main
# =============================================================================
def main():
    """Main entry point."""
    # Log configuration summary
    logger.info("=" * 60)
    logger.info("Audio Preprocessing Service")
    logger.info("=" * 60)
    logger.info(f"Version:         {settings.app_version}")
    logger.info(f"Environment:     {settings.environment}")
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
