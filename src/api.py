"""
FastAPI application for audio processing, health checks, and metrics.
"""

import logging
import io
import time
from typing import Optional
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from .config import settings
from .audio_processor import processor

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
    config: dict


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

# Track processing stats
_processed_count = 0
_error_count = 0


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
        config={
            "vad_enabled": settings.vad.enabled,
            "noise_reduction_enabled": settings.noise.enabled,
            "target_sample_rate": settings.audio.target_sample_rate,
        }
    )


@app.get("/ready", tags=["Health"])
async def readiness_check():
    """Readiness check - service is always ready."""
    return {"status": "ready"}


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
    global _processed_count, _error_count
    total = _processed_count + _error_count
    success_rate = _processed_count / total if total > 0 else 0.0
    uptime = (datetime.now(timezone.utc) - _startup_time).total_seconds()
    
    return StatsResponse(
        processed_count=_processed_count,
        error_count=_error_count,
        success_rate=round(success_rate, 3),
        uptime_seconds=round(uptime, 1)
    )


# =============================================================================
# Processing Endpoints
# =============================================================================
@app.post("/process", tags=["Processing"])
async def process_audio(file: UploadFile = File(...)):
    """
    Process an audio file and return the normalized WAV.
    
    Accepts audio file upload and returns processed 16-bit PCM WAV.
    """
    global _processed_count, _error_count
    
    start_time = time.time()
    
    try:
        # Read the uploaded file into memory
        audio_data = await file.read()
        
        # Check file size
        file_size_mb = len(audio_data) / (1024 * 1024)
        if file_size_mb > settings.processing.max_file_size_mb:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {file_size_mb:.1f}MB (max: {settings.processing.max_file_size_mb}MB)"
            )
        
        # Update metrics
        FILE_SIZE_HISTOGRAM.observe(len(audio_data))
        
        # Process the audio
        logger.info(f"Processing uploaded file: {file.filename} ({file_size_mb:.2f}MB)")
        
        output_audio, stats = processor.process(audio_data, file.filename or "uploaded_audio")
        
        # Update metrics
        duration = time.time() - start_time
        PROCESSING_DURATION.observe(duration)
        PROCESSED_COUNTER.labels(status="success").inc()
        COMPRESSION_RATIO.observe(1 - stats.compression_ratio)
        _processed_count += 1
        
        logger.info(
            f"Processed {file.filename}: "
            f"{stats.original_duration_ms}ms -> {stats.final_duration_ms}ms "
            f"({stats.compression_ratio:.1%} reduction) in {duration:.2f}s"
        )
        
        # Return the processed audio as a streaming response
        return StreamingResponse(
            io.BytesIO(output_audio),
            media_type="audio/wav",
            headers={
                "Content-Disposition": f'attachment; filename="processed_{file.filename}.wav"',
                "X-Processing-Duration-Ms": str(int(duration * 1000)),
                "X-Original-Duration-Ms": str(stats.original_duration_ms),
                "X-Final-Duration-Ms": str(stats.final_duration_ms),
                "X-Compression-Ratio": f"{stats.compression_ratio:.3f}",
            }
        )
        
    except Exception as e:
        duration = time.time() - start_time
        PROCESSED_COUNTER.labels(status="error").inc()
        _error_count += 1
        logger.error(f"Error processing {file.filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.get("/config", tags=["Config"])
async def get_config():
    """Get current configuration (safe values only)."""
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "environment": settings.environment,
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
