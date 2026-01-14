"""
Audio processing pipeline optimized for STT services.

Pipeline stages:
1. Load and decode audio (any format via librosa/soundfile)
2. Resample to target rate (default: 16kHz)
3. Convert to mono
4. Optional: Noise reduction (spectral gating)
5. VAD: Detect speech segments (Silero VAD)
6. Silence compression
7. Normalization
8. Export as 16-bit PCM WAV
"""

import io
import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any

import numpy as np
import soundfile as sf
import librosa

from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class ProcessingStats:
    """Statistics from audio processing."""
    original_duration_ms: int = 0
    final_duration_ms: int = 0
    original_sample_rate: int = 0
    original_channels: int = 0
    speech_segments: int = 0
    silence_removed_ms: int = 0
    noise_reduced: bool = False
    normalized: bool = False
    stages_completed: List[str] = field(default_factory=list)
    
    @property
    def compression_ratio(self) -> float:
        if self.original_duration_ms == 0:
            return 0.0
        return 1.0 - (self.final_duration_ms / self.original_duration_ms)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_duration_ms": self.original_duration_ms,
            "final_duration_ms": self.final_duration_ms,
            "original_sample_rate": self.original_sample_rate,
            "original_channels": self.original_channels,
            "speech_segments": self.speech_segments,
            "silence_removed_ms": self.silence_removed_ms,
            "noise_reduced": self.noise_reduced,
            "normalized": self.normalized,
            "compression_ratio": round(self.compression_ratio, 3),
            "stages_completed": self.stages_completed
        }


class SileroVAD:
    """Wrapper for Silero VAD model with lazy loading."""
    
    _instance = None
    _model = None
    _get_speech_timestamps = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def _load_model(self):
        """Load Silero VAD model (ONNX for efficiency)."""
        if self._model is not None:
            return
        
        try:
            # Try the silero-vad package first
            from silero_vad import load_silero_vad, get_speech_timestamps
            self._model = load_silero_vad(onnx=True)
            self._get_speech_timestamps = get_speech_timestamps
            logger.info("Silero VAD loaded via silero-vad package (ONNX)")
        except ImportError:
            # Fallback to torch.hub
            import torch
            torch.set_num_threads(1)
            model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                onnx=True
            )
            self._model = model
            self._get_speech_timestamps = utils[0]
            logger.info("Silero VAD loaded via torch.hub (ONNX)")
    
    def detect_speech(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000
    ) -> List[Dict[str, int]]:
        """
        Detect speech segments in audio.
        
        Args:
            audio: Audio samples as float32 numpy array
            sample_rate: Sample rate (must be 16000 or 8000 for Silero)
            
        Returns:
            List of dicts with 'start' and 'end' keys (in samples)
        """
        self._load_model()
        
        import torch
        
        # Silero VAD requires 16kHz or 8kHz
        if sample_rate not in (8000, 16000):
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)
            sample_rate = 16000
        
        # Convert to torch tensor
        audio_tensor = torch.from_numpy(audio).float()
        
        # Get speech timestamps
        timestamps = self._get_speech_timestamps(
            audio_tensor,
            self._model,
            sampling_rate=sample_rate,
            threshold=settings.vad.threshold,
            min_speech_duration_ms=settings.vad.min_speech_duration_ms,
            min_silence_duration_ms=settings.vad.min_silence_duration_ms,
            speech_pad_ms=settings.vad.speech_pad_ms,
            window_size_samples=settings.vad.window_size_samples,
            return_seconds=False
        )
        
        return timestamps


class AudioProcessor:
    """Main audio processing pipeline."""
    
    def __init__(self):
        self.vad = SileroVAD() if settings.vad.enabled else None
    
    def process(
        self,
        audio_data: bytes,
        filename: str
    ) -> Tuple[bytes, ProcessingStats]:
        """
        Process audio through the full pipeline.
        
        Args:
            audio_data: Raw audio file bytes
            filename: Original filename (for format detection)
            
        Returns:
            Tuple of (processed WAV bytes, processing stats)
        """
        stats = ProcessingStats()
        
        # Stage 1: Load audio
        logger.info(f"[1/7] Loading audio: {filename}")
        audio, sr, channels = self._load_audio(audio_data, filename)
        
        stats.original_sample_rate = sr
        stats.original_channels = channels
        stats.original_duration_ms = int(len(audio) / sr * 1000)
        stats.stages_completed.append(f"loaded:{sr}Hz,{channels}ch")
        
        logger.info(f"  → {sr}Hz, {channels}ch, {stats.original_duration_ms}ms")
        
        # Stage 2: Resample
        target_sr = settings.audio.target_sample_rate
        if sr != target_sr:
            logger.info(f"[2/7] Resampling: {sr}Hz → {target_sr}Hz")
            audio = librosa.resample(audio, orig_sr=sr, target_sr=target_sr)
            sr = target_sr
            stats.stages_completed.append(f"resampled:{target_sr}Hz")
        else:
            logger.info(f"[2/7] Resampling: skipped (already {sr}Hz)")
            stats.stages_completed.append("resample:skipped")
        
        # Stage 3: Convert to mono
        if audio.ndim > 1 and settings.audio.target_channels == 1:
            logger.info(f"[3/7] Converting to mono")
            audio = np.mean(audio, axis=0) if audio.shape[0] <= 2 else np.mean(audio, axis=1)
            stats.stages_completed.append("mono:converted")
        else:
            logger.info(f"[3/7] Mono conversion: skipped")
            stats.stages_completed.append("mono:skipped")
        
        # Ensure 1D array and float32
        audio = audio.flatten().astype(np.float32)
        
        # Stage 4: Noise reduction
        if settings.noise.enabled:
            logger.info(f"[4/7] Applying noise reduction")
            audio = self._reduce_noise(audio, sr)
            stats.noise_reduced = True
            stats.stages_completed.append("noise_reduction:applied")
        else:
            logger.info(f"[4/7] Noise reduction: disabled")
            stats.stages_completed.append("noise_reduction:disabled")
        
        # Stage 5: VAD
        if settings.vad.enabled and self.vad:
            logger.info(f"[5/7] Running Silero VAD")
            speech_timestamps = self.vad.detect_speech(audio, sr)
            stats.speech_segments = len(speech_timestamps)
            logger.info(f"  → Found {len(speech_timestamps)} speech segments")
            stats.stages_completed.append(f"vad:{len(speech_timestamps)}_segments")
        else:
            logger.info(f"[5/7] VAD: disabled")
            speech_timestamps = [{"start": 0, "end": len(audio)}]
            stats.stages_completed.append("vad:disabled")
        
        # Stage 6: Silence compression
        if settings.silence.enabled and speech_timestamps:
            logger.info(f"[6/7] Compressing silences")
            audio, removed_ms = self._compress_silences(audio, speech_timestamps, sr)
            stats.silence_removed_ms = removed_ms
            logger.info(f"  → Removed {removed_ms}ms of silence")
            stats.stages_completed.append(f"silence_compression:{removed_ms}ms_removed")
        else:
            logger.info(f"[6/7] Silence compression: disabled")
            stats.stages_completed.append("silence_compression:disabled")
        
        # Stage 7: Normalization
        if settings.normalize.enabled:
            logger.info(f"[7/7] Normalizing to {settings.normalize.target_dbfs} dBFS")
            audio = self._normalize(audio, settings.normalize.target_dbfs)
            stats.normalized = True
            stats.stages_completed.append(f"normalized:{settings.normalize.target_dbfs}dBFS")
        else:
            logger.info(f"[7/7] Normalization: disabled")
            stats.stages_completed.append("normalization:disabled")
        
        # Export as 16-bit PCM WAV
        logger.info(f"[Export] Creating WAV output")
        wav_bytes = self._export_wav(audio, sr)
        
        stats.final_duration_ms = int(len(audio) / sr * 1000)
        
        logger.info(
            f"  → Output: {stats.final_duration_ms}ms "
            f"({100 - stats.compression_ratio * 100:.1f}% of original)"
        )
        
        return wav_bytes, stats
    
    def _load_audio(
        self,
        audio_data: bytes,
        filename: str
    ) -> Tuple[np.ndarray, int, int]:
        """Load audio from bytes, return (samples, sample_rate, channels)."""
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        buffer = io.BytesIO(audio_data)
        
        try:
            # Try soundfile first (faster for WAV, FLAC, OGG)
            if ext in ("wav", "flac", "ogg"):
                audio, sr = sf.read(buffer, dtype='float32')
                channels = 1 if audio.ndim == 1 else audio.shape[1]
                return audio, sr, channels
        except Exception:
            buffer.seek(0)
        
        # Use librosa for everything else (uses ffmpeg via audioread)
        audio, sr = librosa.load(buffer, sr=None, mono=False)
        
        # librosa returns (samples,) for mono, (channels, samples) for stereo
        if audio.ndim == 1:
            channels = 1
        else:
            channels = audio.shape[0]
            audio = audio.T  # Transpose to (samples, channels)
        
        return audio, sr, channels
    
    def _reduce_noise(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Apply spectral gating noise reduction."""
        try:
            import noisereduce as nr
            return nr.reduce_noise(
                y=audio,
                sr=sr,
                stationary=settings.noise.stationary,
                prop_decrease=settings.noise.prop_decrease,
                n_fft=settings.noise.n_fft,
                n_jobs=1
            )
        except Exception as e:
            logger.warning(f"Noise reduction failed: {e}")
            return audio
    
    def _compress_silences(
        self,
        audio: np.ndarray,
        speech_segments: List[Dict[str, int]],
        sr: int
    ) -> Tuple[np.ndarray, int]:
        """Compress long silences between speech segments."""
        if not speech_segments:
            return audio, 0
        
        max_gap_samples = int(settings.silence.max_gap_ms * sr / 1000)
        keep_samples = int(settings.silence.keep_ms * sr / 1000)
        
        chunks = []
        total_removed = 0
        
        for i, seg in enumerate(speech_segments):
            # Add speech segment
            chunks.append(audio[seg["start"]:seg["end"]])
            
            # Handle gap to next segment
            if i < len(speech_segments) - 1:
                gap_start = seg["end"]
                gap_end = speech_segments[i + 1]["start"]
                gap_length = gap_end - gap_start
                
                if gap_length > max_gap_samples:
                    # Compress: keep only specified silence
                    chunks.append(np.zeros(keep_samples, dtype=audio.dtype))
                    total_removed += gap_length - keep_samples
                elif gap_length > 0:
                    # Keep original gap
                    chunks.append(audio[gap_start:gap_end])
        
        removed_ms = int(total_removed * 1000 / sr)
        return np.concatenate(chunks), removed_ms
    
    def _normalize(self, audio: np.ndarray, target_dbfs: float) -> np.ndarray:
        """Normalize audio to target dBFS level."""
        rms = np.sqrt(np.mean(audio ** 2))
        if rms == 0:
            return audio
        
        current_dbfs = 20 * np.log10(rms + 1e-10)
        gain_db = target_dbfs - current_dbfs
        gain_linear = 10 ** (gain_db / 20)
        
        normalized = audio * gain_linear
        
        # Prevent clipping
        peak = np.max(np.abs(normalized))
        if peak > 0.99:
            normalized = normalized * (0.99 / peak)
        
        return normalized
    
    def _export_wav(self, audio: np.ndarray, sr: int) -> bytes:
        """Export audio as 16-bit PCM WAV."""
        # Convert to 16-bit integers
        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        
        buffer = io.BytesIO()
        sf.write(buffer, audio_int16, sr, format='WAV', subtype='PCM_16')
        
        return buffer.getvalue()


# Global processor instance
processor = AudioProcessor()
