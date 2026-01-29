# Audio Preprocessing Requirements & Specifications

---

## Overview

This module preprocesses call-center audio recordings to optimize them for Microsoft Whisper speech-to-text transcription. The preprocessing pipeline applies a series of signal processing operations to enhance speech clarity and reduce noise.

---

## Processing Pipeline

The preprocessing follows this sequential order:

### 1. **Audio Loading**
- **Sample Rate**: 16 kHz (mandatory)
- **Channels**: Mono (single channel)
- **Format**: WAV input expected
- **Loader**: Uses Whisper's `load_audio()` function to handle non-seekable files
- **Error Handling**: If loading fails, preprocessing is skipped and original file is returned

### 2. **DC Offset Removal**
- **Operation**: Subtract the mean value from all samples
- **Purpose**: Remove any DC bias in the signal
- **Formula**: `y = y - mean(y)`

### 3. **Noise Reduction** (Optional)
- **Library**: noisereduce
- **Method**: Spectral gating/subtraction
- **Noise Reference**: First 0.5 seconds of audio (if available)
- **Reduction Strength**: 60% (`prop_decrease=0.6`)
- **Configurable**: Can be disabled via `use_noise_reduction=False`
- **Default**: Enabled

### 4. **Telephone-Band Emphasis (Bandpass Filtering)**

#### High-Pass Filter
- **Purpose**: Remove low-frequency rumble and background noise
- **Cutoff Frequency**: 80 Hz (default)
- **Filter Type**: Butterworth
- **Filter Order**: 4th order
- **Implementation**: `scipy.signal.butter()` + `lfilter()`
- **Configurable**: `hp_cutoff` parameter
- **Bypass**: Set to `None` or `0` to disable

#### Low-Pass Filter
- **Purpose**: Remove high-frequency noise above telephone bandwidth
- **Cutoff Frequency**: 3800 Hz (default)
- **Filter Type**: Butterworth
- **Filter Order**: 4th order
- **Implementation**: `scipy.signal.butter()` + `lfilter()`
- **Configurable**: `lp_cutoff` parameter
- **Bypass**: Set to `None`, `0`, or `>= sr/2` to disable

**Combined Effect**: Creates a bandpass filter (80 Hz - 3800 Hz) mimicking telephone frequency response

### 5. **RMS Normalization**
- **Purpose**: Normalize audio loudness for consistent volume
- **Target RMS**: 0.1 (default)
- **Method**: 
  - Calculate current RMS: `sqrt(mean(y²))`
  - Calculate gain: `target_rms / (current_rms + 1e-6)`
  - Clamp gain: `[0.1, 10.0]` (prevents extreme amplification/attenuation)
  - Apply: `y = y * gain`
- **Safety**: Zero-division protection with epsilon (1e-6)

### 6. **Silence Trimming**
- **Library**: librosa
- **Method**: `librosa.effects.trim()`
- **Threshold**: 25 dB below peak (default)
- **Purpose**: Remove leading and trailing silence
- **Configurable**: `trim_db` parameter

### 7. **Final Safety Processing**
- **Clipping**: Values clamped to [-1.0, 1.0] range to prevent overflow
- **Data Type**: Convert to `float32` (32-bit floating point)

### 8. **Output**
- **Format**: WAV file
- **Sample Rate**: 16 kHz (same as input)
- **Channels**: Mono
- **Default Naming**: `{original_stem}_clean.wav`
- **Library**: soundfile (`sf.write()`)

---

## Function Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `input_wav` | str \| Path | Required | Path to input audio file |
| `output_wav` | str \| Path \| None | None | Output path (auto-generated if None) |
| `sr` | int | 16000 | Sample rate in Hz |
| `target_rms` | float | 0.1 | Target RMS loudness level |
| `use_noise_reduction` | bool | True | Enable/disable noise reduction |
| `hp_cutoff` | float | 80.0 | High-pass filter cutoff (Hz) |
| `lp_cutoff` | float | 3800.0 | Low-pass filter cutoff (Hz) |
| `trim_db` | float | 25.0 | Silence trim threshold (dB) |

---

## Technical Requirements

### Signal Processing Details

**High-Pass Butterworth Filter Design:**
```
Order: 4
Type: highpass
Normalized cutoff: cutoff / (sr / 2)
Output: ba coefficients
```

**Low-Pass Butterworth Filter Design:**
```
Order: 4
Type: lowpass
Normalized cutoff: cutoff / (sr / 2)
Output: ba coefficients
```

**Filter Application:**
```
Method: lfilter (time-domain IIR filtering)
Direction: Forward only (introduces phase shift)
```

---

## Performance Characteristics

### Target Audio Profile
- **Domain**: Call center recordings
- **Expected Quality**: Telephone-quality audio (300-3400 Hz bandwidth typically)
- **Common Issues Addressed**:
  - Background noise
  - Inconsistent volume levels
  - DC offset
  - Low-frequency rumble
  - High-frequency hiss
  - Leading/trailing silence

### Processing Order Rationale
1. DC removal first (prevents filter artifacts)
2. Noise reduction early (works on full spectrum)
3. Bandpass filtering (shapes frequency response)
4. Normalization after filtering (compensates for filter gain)
5. Trimming last (removes silence created by previous steps)

---

## Refactoring Considerations

### Alternative Technologies

#### 1. **FFmpeg with Audio Filters** (Recommended)
**Advantages:**
- Fast, native C implementation
- No Python dependencies
- Can process in streaming mode
- Industry-standard tool

**Equivalent FFmpeg Command:**
```bash
ffmpeg -i input.wav \
  -af "highpass=f=80, \
       lowpass=f=3800, \
       afftdn=nf=-25, \
       dynaudnorm=r=0.1, \
       silenceremove=start_periods=1:start_threshold=-25dB:stop_periods=1:stop_threshold=-25dB" \
  -ar 16000 -ac 1 -sample_fmt s16 output_clean.wav
```

**Filter Mapping:**
- `highpass=f=80` → High-pass filter
- `lowpass=f=3800` → Low-pass filter
- `afftdn` → FFT-based noise reduction
- `dynaudnorm` → Dynamic audio normalization
- `silenceremove` → Trim silence
- `-ar 16000` → Resample to 16 kHz
- `-ac 1` → Convert to mono

---

## Recommended Refactoring Strategy

### Option A: FFmpeg-based (Production-Ready)
**Best for:** Scalability, performance, minimal dependencies

```python
import subprocess
from pathlib import Path

def preprocess_with_ffmpeg(input_wav: str, output_wav: str = None) -> str:
    input_path = Path(input_wav)
    output_path = Path(output_wav) if output_wav else input_path.with_name(
        input_path.stem + "_clean.wav"
    )
    
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", (
            "highpass=f=80,"
            "lowpass=f=3800,"
            "afftdn=nf=-25:tn=1,"
            "dynaudnorm=p=0.95:m=10:r=0.1,"
            "silenceremove=start_periods=1:start_threshold=-25dB:"
            "stop_periods=-1:stop_threshold=-25dB"
        ),
        "-ar", "16000",
        "-ac", "1",
        "-sample_fmt", "s16",
        str(output_path)
    ]
    
    subprocess.run(cmd, check=True, capture_output=True)
    return str(output_path)
```
---

## Quality Improvements to Consider

1. **Better Noise Reduction**: Replace noisereduce with:
   - Facebook's Denoiser (real-time capable)
   - DTLN (Dual-signal Transformation LSTM Network)
   - Resemble Enhance

2. **Voice Activity Detection (VAD)**: More sophisticated silence detection:
   - WebRTC VAD
   - Silero VAD
   - pyannote.audio

3. **Speaker Diarization Preprocessing**: If needed downstream

4. **Adaptive Filtering**: Adjust parameters based on audio characteristics

5. **Phase-Preserving Filters**: Use `filtfilt` instead of `lfilter` for zero-phase filtering

---

This documentation provides a complete specification for reimplementing the audio preprocessing in any technology stack while maintaining equivalent or improved quality.
