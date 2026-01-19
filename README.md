# Audio Preprocessing Service

A high-performance, containerized service for preprocessing audio files before speech-to-text (STT) processing. Optimized for Whisper and similar services.

## Features

### 🎯 Whisper-Optimized Output
- **16kHz mono 16-bit PCM WAV** - Optimal format for STT engines
- Automatic format conversion (MP3, M4A, AAC, FLAC, OGG, etc.)
- High-quality resampling via librosa

### 🎤 Enterprise-Grade VAD
- **Silero VAD** with ONNX Runtime - ML-based, 6000+ languages
- <1ms inference per audio chunk
- Configurable thresholds

### 🔇 Smart Silence Compression
- Detect and compress long pauses
- Reduce file sizes and STT costs
- Preserve natural speech rhythm

### 🔊 Optional Noise Reduction
- Spectral gating via `noisereduce`
- Ideal for call center/telephony audio

### 📊 Observability
- Prometheus metrics endpoint
- Health and readiness checks
- Structured JSON logging

## Architecture

```
┌─────────────┐
│   Client    │
│ (cURL/API)  │
└──────┬──────┘
       │ POST /process (audio binary)
       │
       ▼
┌─────────────────┐
│  FastAPI App    │
│ ┌─────────────┐ │
│ │  Audio      │ │
│ │  Processor  │ │
│ └─────────────┘ │
└────────┬────────┘
         │
         ▼ Returns processed WAV
    ┌─────────┐
    │ Client  │
    └─────────┘
```

## Quick Start

### Local Development

```bash
# Clone the repository
git clone <repo>
cd stt-audio-preprocess

# Start with Docker Compose
docker compose up --build

# Process an audio file
curl -X POST "http://localhost:8080/process" \
  -F "file=@test_audio.mp3" \
  -o processed.wav

# Or with raw binary
curl -X POST "http://localhost:8080/process" \
  -H "Content-Type: audio/mpeg" \
  --data-binary "@test_audio.mp3" \
  -o processed.wav
```

### Running Locally (Python)

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (optional)
export VAD_ENABLED=true
export NOISE_ENABLED=false

# Run the service
python -m src.main

# Or with uvicorn directly
uvicorn src.main:api_app --host 0.0.0.0 --port 8080
```

## API Reference

### POST /process

Process an audio file and return the normalized WAV.

**Request:**
- **Method:** `POST`
- **Content-Type:** `multipart/form-data` (with file upload) OR `audio/*` (raw binary)
- **Body:** Audio file as binary data

**Response:**
- **Content-Type:** `audio/wav`
- **Body:** Processed 16-bit PCM WAV file

**Headers (response):**
- `X-Processing-Duration-Ms`: Processing time in milliseconds
- `X-Original-Duration-Ms`: Original audio duration
- `X-Final-Duration-Ms`: Final audio duration after processing
- `X-Compression-Ratio`: Ratio of silence removed (0.0-1.0)

**Example with multipart/form-data:**
```bash
curl -X POST "http://localhost:8080/process" \
  -F "file=@input.mp3" \
  -o output.wav
```

**Example with raw binary:**
```bash
curl -X POST "http://localhost:8080/process" \
  -H "Content-Type: audio/mpeg" \
  --data-binary "@input.mp3" \
  -o output.wav
```

**Example with Python:**
```python
import requests

with open("input.mp3", "rb") as f:
    response = requests.post(
        "http://localhost:8080/process",
        files={"file": f}
    )

with open("output.wav", "wb") as f:
    f.write(response.content)
```

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z",
  "version": "2.0.0",
  "environment": "production",
  "config": {
    "vad_enabled": true,
    "noise_reduction_enabled": false,
    "target_sample_rate": 16000
  }
}
```

### GET /ready

Readiness check endpoint. Always returns ready since there are no external dependencies.

**Response:**
```json
{
  "status": "ready"
}
```

### GET /metrics

Prometheus metrics endpoint.

**Example metrics:**
```
# Total files processed
audio_files_processed_total{status="success"} 1234
audio_files_processed_total{status="error"} 5

# Processing duration histogram
audio_processing_duration_seconds_bucket{le="10"} 1200
audio_processing_duration_seconds_bucket{le="30"} 1230

# Compression ratio
audio_compression_ratio_bucket{le="0.5"} 800
```

### GET /stats

Get processing statistics.

**Response:**
```json
{
  "processed_count": 1234,
  "error_count": 5,
  "success_rate": 0.996,
  "uptime_seconds": 86400.0
}
```

### GET /config

Get current configuration.

**Response:**
```json
{
  "app_name": "audio-preprocess",
  "app_version": "2.0.0",
  "environment": "production",
  "audio": {
    "target_sample_rate": 16000,
    "target_channels": 1,
    "supported_extensions": [".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"]
  },
  "vad": {
    "enabled": true,
    "threshold": 0.5,
    "min_speech_duration_ms": 250
  },
  "silence": {
    "enabled": true,
    "max_gap_ms": 600,
    "keep_ms": 150
  },
  "noise": {
    "enabled": false,
    "stationary": true
  },
  "normalize": {
    "enabled": true,
    "target_dbfs": -20.0
  }
}
```

## Configuration

### Environment Variables

See [.env.example](.env.example) for all options.

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIO_TARGET_SAMPLE_RATE` | `16000` | Output sample rate in Hz |
| `AUDIO_TARGET_CHANNELS` | `1` | Output channels (1=mono) |
| `VAD_ENABLED` | `true` | Enable Silero VAD |
| `VAD_THRESHOLD` | `0.5` | Speech probability threshold (0.0-1.0) |
| `NOISE_ENABLED` | `false` | Enable spectral noise reduction |
| `SILENCE_ENABLED` | `true` | Enable silence compression |
| `SILENCE_MAX_GAP_MS` | `600` | Compress gaps longer than this |
| `SILENCE_KEEP_MS` | `150` | Silence to keep after compression |
| `NORMALIZE_ENABLED` | `true` | Enable audio normalization |
| `NORMALIZE_TARGET_DBFS` | `-20.0` | Target loudness in dBFS |

## Deployment

### Docker

```bash
# Build the image
docker build -t audio-preprocess .

# Run the container
docker run -p 8080:8080 \
  -e VAD_ENABLED=true \
  -e NOISE_ENABLED=false \
  audio-preprocess
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: audio-preprocess
spec:
  replicas: 3
  selector:
    matchLabels:
      app: audio-preprocess
  template:
    metadata:
      labels:
        app: audio-preprocess
    spec:
      containers:
      - name: audio-preprocess
        image: your-registry/audio-preprocess:latest
        ports:
        - containerPort: 8080
        env:
        - name: VAD_ENABLED
          value: "true"
        - name: SILENCE_ENABLED
          value: "true"
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
```

## Performance

Benchmarks (1 CPU, 2GB RAM):

| Audio Duration | Processing Time | Compression |
|----------------|-----------------|-------------|
| 1 minute | 2-4 seconds | 30-50% |
| 10 minutes | 15-30 seconds | 25-45% |
| 1 hour | 2-4 minutes | 20-40% |

## Troubleshooting

### Common Issues

**"Failed to load audio"**
- Check FFmpeg is installed: `docker exec <container> ffmpeg -version`
- Verify file format is supported

**"VAD model not found"**
- Ensure `silero-vad` and `onnxruntime` are installed
- Check internet access for model download on first run

**"File too large"**
- Increase `PROCESSING_MAX_FILE_SIZE_MB` environment variable
- Default is 500MB

### Debug Mode

Enable detailed logging:
```bash
DEBUG=true
SERVER_LOG_LEVEL=debug
```

## License

MIT License
