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

# OCI Labels
LABEL org.opencontainers.image.source=https://github.com/kayaman/stt-audio-preprocess
LABEL org.opencontainers.image.description="State-of-the-art audio preprocessing service for Speech-to-Text"
LABEL org.opencontainers.image.licenses=MIT
LABEL org.opencontainers.image.title="STT Audio Preprocess"
LABEL org.opencontainers.image.version="2.0.0"
LABEL org.opencontainers.image.vendor="kayaman"
LABEL org.opencontainers.image.authors="kayaman"
LABEL org.opencontainers.image.documentation=https://github.com/kayaman/stt-audio-preprocess/blob/main/README.md

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

# Create non-root user for security (UID 65532 for consistency with Helm chart)
RUN useradd --uid 65532 --create-home --shell /bin/bash appuser && \
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
