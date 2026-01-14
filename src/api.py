"""
FastAPI application for health checks, metrics, and manual processing.
"""

import logging
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from .config import settings
from .blob_handler import blob_handler, BlobInfo
from .queue_listener import worker, queue_listener, polling_listener

logger = logging.getLogger(__name__)

# =============================================================================
# Prometheus Metrics
# =============================================================================
PROCESSED_COUNTER = Counter(
    'audio_files_processed_total',
    'Total number of audio files processed',
    ['status']
)

PROCESSING_DURATION = Histogram(
    'audio_processing_duration_seconds',
    'Audio processing duration in seconds',
    buckets=[1, 5, 10, 30, 60, 120, 300, 600]
)

FILE_SIZE_HISTOGRAM = Histogram(
    'audio_file_size_bytes',
    'Input audio file size in bytes',
    buckets=[1e5, 1e6, 5e6, 1e7, 5e7, 1e8, 5e8]
)

COMPRESSION_RATIO = Histogram(
    'audio_compression_ratio',
    'Output size as ratio of input size',
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)


# =============================================================================
# API Models
# =============================================================================
class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    environment: str
    processing_mode: str
    config: dict


class ProcessRequest(BaseModel):
    container: str = Field(..., description="Source blob container")
    blob_name: str = Field(..., description="Source blob name/path")


class ProcessResponse(BaseModel):
    success: bool
    input_path: str
    output_path: Optional[str] = None
    stats: Optional[dict] = None
    error: Optional[str] = None
    duration_seconds: float


class BlobListResponse(BaseModel):
    count: int
    blobs: List[dict]


class StatsResponse(BaseModel):
    processed_count: int
    error_count: int
    success_rate: float
    uptime_seconds: float


# =============================================================================
# FastAPI Application
# =============================================================================
app = FastAPI(
    title="Audio Preprocessing Service",
    description="Preprocess audio files for speech-to-text services",
    version=settings.app_version,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None
)

# Track startup time
_startup_time = datetime.now(timezone.utc)


# =============================================================================
# Health & Metrics Endpoints
# =============================================================================
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint for container orchestration."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=settings.app_version,
        environment=settings.environment,
        processing_mode=settings.processing_mode,
        config={
            "vad_enabled": settings.vad.enabled,
            "noise_reduction_enabled": settings.noise.enabled,
            "target_sample_rate": settings.audio.target_sample_rate,
            "container_input": settings.azure.container_input,
            "container_output": settings.azure.container_output,
        }
    )


@app.get("/ready", tags=["Health"])
async def readiness_check():
    """Readiness check - verifies Azure Storage connectivity."""
    try:
        # Try to list containers (minimal operation)
        _ = blob_handler.client.list_containers(max_results=1)
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Not ready: {e}")


@app.get("/metrics", tags=["Metrics"])
async def metrics():
    """Prometheus metrics endpoint."""
    return JSONResponse(
        content=generate_latest().decode('utf-8'),
        media_type=CONTENT_TYPE_LATEST
    )


@app.get("/stats", response_model=StatsResponse, tags=["Metrics"])
async def get_stats():
    """Get processing statistics."""
    total = worker.processed_count + worker.error_count
    success_rate = worker.processed_count / total if total > 0 else 0.0
    uptime = (datetime.now(timezone.utc) - _startup_time).total_seconds()
    
    return StatsResponse(
        processed_count=worker.processed_count,
        error_count=worker.error_count,
        success_rate=round(success_rate, 3),
        uptime_seconds=round(uptime, 1)
    )


# =============================================================================
# Processing Endpoints
# =============================================================================
@app.post("/process", response_model=ProcessResponse, tags=["Processing"])
async def process_blob(request: ProcessRequest):
    """
    Process a single blob manually.
    
    Use this for testing or reprocessing failed files.
    """
    blob_info = blob_handler.get_blob_info(request.container, request.blob_name)
    
    if not blob_info:
        raise HTTPException(status_code=404, detail="Blob not found")
    
    # Check extension
    ext = f".{blob_info.extension}"
    if ext not in settings.audio.supported_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {ext}. Supported: {settings.audio.supported_extensions}"
        )
    
    # Process
    result = worker.process_blob(blob_info)
    
    # Update metrics
    PROCESSED_COUNTER.labels(status="success" if result.success else "error").inc()
    PROCESSING_DURATION.observe(result.duration_seconds)
    
    if result.stats:
        FILE_SIZE_HISTOGRAM.observe(result.stats.original_duration_ms * 16 * 2)  # Approximate bytes
        COMPRESSION_RATIO.observe(1 - result.stats.compression_ratio)
    
    return ProcessResponse(
        success=result.success,
        input_path=result.input_path,
        output_path=result.output_path,
        stats=result.stats.to_dict() if result.stats else None,
        error=result.error,
        duration_seconds=result.duration_seconds
    )


@app.post("/process/batch", tags=["Processing"])
async def process_batch(
    background_tasks: BackgroundTasks,
    container: str = Query(default=None, description="Override input container"),
    prefix: str = Query(default=None, description="Override input prefix"),
    limit: int = Query(default=100, le=1000, description="Maximum files to process")
):
    """
    Process multiple blobs in the background.
    
    Useful for bulk reprocessing.
    """
    container = container or settings.azure.container_input
    prefix = prefix or settings.azure.folder_input
    
    # List blobs
    blobs = blob_handler.list_blobs(
        container,
        prefix=prefix,
        extensions=settings.audio.supported_extensions
    )[:limit]
    
    if not blobs:
        return {"message": "No files to process", "count": 0}
    
    # Add background task
    def process_all():
        for blob_info in blobs:
            result = worker.process_blob(blob_info)
            PROCESSED_COUNTER.labels(status="success" if result.success else "error").inc()
            PROCESSING_DURATION.observe(result.duration_seconds)
    
    background_tasks.add_task(process_all)
    
    return {
        "message": f"Processing {len(blobs)} files in background",
        "count": len(blobs),
        "files": [b.name for b in blobs[:10]]  # Show first 10
    }


@app.get("/blobs", response_model=BlobListResponse, tags=["Storage"])
async def list_input_blobs(
    container: str = Query(default=None, description="Container name"),
    prefix: str = Query(default=None, description="Blob prefix"),
    limit: int = Query(default=100, le=1000, description="Maximum results")
):
    """List blobs in the input container."""
    container = container or settings.azure.container_input
    prefix = prefix or settings.azure.folder_input
    
    blobs = blob_handler.list_blobs(
        container,
        prefix=prefix,
        extensions=settings.audio.supported_extensions
    )[:limit]
    
    return BlobListResponse(
        count=len(blobs),
        blobs=[
            {
                "name": b.name,
                "size": b.size,
                "content_type": b.content_type,
                "last_modified": b.last_modified.isoformat() if b.last_modified else None
            }
            for b in blobs
        ]
    )


# =============================================================================
# Control Endpoints
# =============================================================================
@app.post("/control/pause", tags=["Control"])
async def pause_processing():
    """Pause background processing."""
    queue_listener.stop()
    polling_listener.stop()
    return {"status": "paused"}


@app.get("/config", tags=["Config"])
async def get_config():
    """Get current configuration (safe values only)."""
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "environment": settings.environment,
        "processing_mode": settings.processing_mode,
        "audio": {
            "target_sample_rate": settings.audio.target_sample_rate,
            "target_channels": settings.audio.target_channels,
            "supported_extensions": settings.audio.supported_extensions
        },
        "vad": {
            "enabled": settings.vad.enabled,
            "threshold": settings.vad.threshold,
            "min_speech_duration_ms": settings.vad.min_speech_duration_ms
        },
        "silence": {
            "enabled": settings.silence.enabled,
            "max_gap_ms": settings.silence.max_gap_ms,
            "keep_ms": settings.silence.keep_ms
        },
        "noise": {
            "enabled": settings.noise.enabled,
            "stationary": settings.noise.stationary
        },
        "normalize": {
            "enabled": settings.normalize.enabled,
            "target_dbfs": settings.normalize.target_dbfs
        }
    }
