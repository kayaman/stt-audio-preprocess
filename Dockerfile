# =============================================================================
# Audio Preprocessing Container
# Optimized for Speech-to-Text services (Whisper, Azure Speech, etc.)
# =============================================================================

# Build stage for smaller final image
FROM python:3.12-slim-bookworm AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# =============================================================================
# Production image
# =============================================================================
FROM python:3.12-slim-bookworm AS production

# Labels
LABEL maintainer="Audio Processing Team"
LABEL description="Audio preprocessing for STT services"
LABEL version="2.0.0"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # FFmpeg for audio format conversion (MP3, M4A, AAC, etc.)
    ffmpeg \
    # libsndfile for soundfile library
    libsndfile1 \
    # Required for some audio codecs
    libavcodec-extra \
    # Useful for debugging
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port for health checks and metrics
EXPOSE 8080

# Default command
CMD ["python", "-m", "src.main"]
