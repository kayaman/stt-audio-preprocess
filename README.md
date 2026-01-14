# Audio Preprocessing Service (Containerized)

A high-performance, containerized service for preprocessing audio files before speech-to-text (STT) processing. Optimized for Whisper and similar services.

## Why Containerized?

| Feature | Azure Functions | Container Apps |
|---------|-----------------|----------------|
| FFmpeg support | Requires custom image | ✅ Native |
| System libraries | Limited | ✅ Full control |
| Cold starts | Can be slow | ✅ Faster with min replicas |
| Scaling | Event-driven | ✅ Event-driven (KEDA) |
| Cost | Consumption billing | ✅ Scale to zero |
| Complexity | Simple for small scale | Better for production |

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
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Blob Storage   │────▶│  Event Grid     │────▶│  Storage Queue  │
│  (audio-input)  │     │  Subscription   │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
                                               ┌─────────────────┐
                                               │  Container App  │
                                               │  ┌───────────┐  │
                                               │  │  FastAPI  │  │
                                               │  │  + Worker │  │
                                               │  └───────────┘  │
                                               └────────┬────────┘
                                                        │
                                                        ▼
                                               ┌─────────────────┐
                                               │  Blob Storage   │
                                               │  (audio-output) │
                                               └─────────────────┘
```

## Quick Start

### Local Development

```bash
# Clone and start
git clone <repo>
cd audio-preprocess-container

# Start with Docker Compose (includes Azurite)
docker compose up --build

# Wait for setup, then upload a test file
curl -X POST "http://localhost:8080/process" \
  -H "Content-Type: application/json" \
  -d '{"container": "audio-input", "blob_name": "incoming/test.wav"}'
```

### Deploy to Azure Container Apps

```bash
# Set your configuration
export RESOURCE_GROUP=rg-audio-preprocess
export STORAGE_ACCOUNT=staudiopreprocess
export ACR_NAME=acraudiopreprocess

# Deploy
chmod +x deploy/deploy.sh
./deploy/deploy.sh production

# Set up Event Grid triggers
./deploy/setup-eventgrid.sh $RESOURCE_GROUP $STORAGE_ACCOUNT
```

## Configuration

### Environment Variables

See [.env.example](.env.example) for all options.

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `PROCESSING_MODE` | `queue` | `queue`, `polling`, or `manual` |
| `VAD_ENABLED` | `true` | Enable Silero VAD |
| `VAD_THRESHOLD` | `0.5` | Speech probability threshold |
| `NOISE_ENABLED` | `false` | Enable spectral noise reduction |
| `SILENCE_ENABLED` | `true` | Enable silence compression |
| `SILENCE_MAX_GAP_MS` | `600` | Compress gaps longer than this |

### Processing Modes

**Queue Mode (Recommended)**
- Event-driven via Azure Storage Queue
- Events from Event Grid blob triggers
- Best for production at scale

**Polling Mode**
- Periodically scans input container
- Simpler setup, no Event Grid needed
- Good for development/testing

**Manual Mode**
- API-only, no background processing
- Use for testing or on-demand processing

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/ready` | GET | Readiness check |
| `/metrics` | GET | Prometheus metrics |
| `/stats` | GET | Processing statistics |
| `/process` | POST | Process single blob |
| `/process/batch` | POST | Process multiple blobs |
| `/blobs` | GET | List input blobs |
| `/config` | GET | View configuration |

### Example: Process a file

```bash
curl -X POST "https://your-service.azurecontainerapps.io/process" \
  -H "Content-Type: application/json" \
  -d '{
    "container": "audio-input",
    "blob_name": "incoming/call_123.mp3"
  }'
```

Response:
```json
{
  "success": true,
  "input_path": "audio-input/incoming/call_123.mp3",
  "output_path": "audio-output/processed/call_123.wav",
  "stats": {
    "original_duration_ms": 180000,
    "final_duration_ms": 145000,
    "speech_segments": 42,
    "silence_removed_ms": 35000,
    "compression_ratio": 0.194
  },
  "duration_seconds": 12.5
}
```

## Scaling

### Azure Container Apps Scaling Rules

The default deployment scales based on queue length:

```yaml
scale:
  minReplicas: 0      # Scale to zero when idle
  maxReplicas: 10     # Maximum instances
  rules:
    - name: queue-scaling
      azureQueue:
        queueName: audio-processing-queue
        queueLength: 10  # Messages per instance
```

### Recommended Resources

| Workload | CPU | Memory | Max Replicas |
|----------|-----|--------|--------------|
| Light (<1k/day) | 0.5 | 1Gi | 3 |
| Medium (1k-10k/day) | 1.0 | 2Gi | 5 |
| Heavy (10k+/day) | 2.0 | 4Gi | 10+ |

## Monitoring

### Prometheus Metrics

```
# Total files processed
audio_files_processed_total{status="success"}
audio_files_processed_total{status="error"}

# Processing duration histogram
audio_processing_duration_seconds_bucket{le="10"}
audio_processing_duration_seconds_bucket{le="30"}

# Compression ratio
audio_compression_ratio_bucket{le="0.5"}
```

### Health Checks

```bash
# Liveness
curl https://your-service/health

# Readiness (checks Azure Storage connectivity)
curl https://your-service/ready
```

## Troubleshooting

### Common Issues

**"Failed to load audio"**
- Check FFmpeg is installed: `docker exec <container> ffmpeg -version`
- Verify file format is supported

**"VAD model not found"**
- Ensure `silero-vad` and `onnxruntime` are installed
- Check internet access for model download on first run

**"Queue messages not processing"**
- Verify Event Grid subscription is active
- Check queue name matches configuration
- Ensure storage connection string is correct

### Debug Mode

Enable detailed logging:
```bash
DEBUG=true
SERVER_LOG_LEVEL=debug
```

## Performance

Benchmarks on Azure Container Apps (1 CPU, 2GB RAM):

| Audio Duration | Processing Time | Compression |
|----------------|-----------------|-------------|
| 1 minute | 2-4 seconds | 30-50% |
| 10 minutes | 15-30 seconds | 25-45% |
| 1 hour | 2-4 minutes | 20-40% |

## License

MIT License
