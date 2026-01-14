"""
Configuration management using Pydantic Settings.

All configuration is loaded from environment variables with sensible defaults.
"""

from typing import Optional, Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureSettings(BaseSettings):
    """Azure Storage configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix="AZURE_",
        env_file=".env",
        extra="ignore"
    )
    
    # Connection strings
    storage_connection_string: str = Field(
        default="",
        description="Azure Storage connection string"
    )
    
    # Alternatively, use managed identity
    storage_account_name: str = Field(
        default="",
        description="Storage account name (for managed identity)"
    )
    
    # Containers
    container_input: str = Field(
        default="audio-input",
        description="Input blob container"
    )
    container_output: str = Field(
        default="audio-output", 
        description="Output blob container"
    )
    
    # Folders (prefixes)
    folder_input: str = Field(
        default="incoming",
        description="Input folder prefix"
    )
    folder_output: str = Field(
        default="processed",
        description="Output folder prefix"
    )
    
    # Queue for event-driven processing
    queue_name: str = Field(
        default="audio-processing-queue",
        description="Storage queue for blob events"
    )
    
    # Delete source after processing
    delete_source: bool = Field(
        default=True,
        description="Delete source blob after successful processing"
    )


class AudioSettings(BaseSettings):
    """Audio processing configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix="AUDIO_",
        env_file=".env",
        extra="ignore"
    )
    
    # Output format (Whisper-optimized defaults)
    target_sample_rate: int = Field(
        default=16000,
        description="Output sample rate in Hz"
    )
    target_channels: int = Field(
        default=1,
        description="Output channels (1=mono, 2=stereo)"
    )
    target_bit_depth: int = Field(
        default=16,
        description="Output bit depth"
    )
    
    # Supported input formats
    supported_extensions: tuple = (
        ".wav", ".mp3", ".m4a", ".aac", ".flac", 
        ".ogg", ".opus", ".wma", ".webm", ".mp4"
    )


class VADSettings(BaseSettings):
    """Voice Activity Detection settings (Silero VAD)."""
    
    model_config = SettingsConfigDict(
        env_prefix="VAD_",
        env_file=".env",
        extra="ignore"
    )
    
    enabled: bool = Field(
        default=True,
        description="Enable voice activity detection"
    )
    threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Speech probability threshold"
    )
    min_speech_duration_ms: int = Field(
        default=250,
        description="Minimum speech segment duration in ms"
    )
    min_silence_duration_ms: int = Field(
        default=100,
        description="Minimum silence to split segments in ms"
    )
    speech_pad_ms: int = Field(
        default=30,
        description="Padding around speech segments in ms"
    )
    window_size_samples: int = Field(
        default=512,
        description="VAD window size in samples"
    )


class SilenceCompressionSettings(BaseSettings):
    """Silence compression settings."""
    
    model_config = SettingsConfigDict(
        env_prefix="SILENCE_",
        env_file=".env",
        extra="ignore"
    )
    
    enabled: bool = Field(
        default=True,
        description="Enable silence compression"
    )
    max_gap_ms: int = Field(
        default=600,
        description="Compress gaps longer than this (ms)"
    )
    keep_ms: int = Field(
        default=150,
        description="Silence to keep after compression (ms)"
    )


class NoiseReductionSettings(BaseSettings):
    """Noise reduction settings."""
    
    model_config = SettingsConfigDict(
        env_prefix="NOISE_",
        env_file=".env",
        extra="ignore"
    )
    
    enabled: bool = Field(
        default=False,
        description="Enable spectral noise reduction"
    )
    stationary: bool = Field(
        default=True,
        description="Use stationary noise reduction"
    )
    prop_decrease: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Noise reduction strength"
    )
    n_fft: int = Field(
        default=512,
        description="FFT size (512 optimal for speech)"
    )


class NormalizationSettings(BaseSettings):
    """Audio normalization settings."""
    
    model_config = SettingsConfigDict(
        env_prefix="NORMALIZE_",
        env_file=".env",
        extra="ignore"
    )
    
    enabled: bool = Field(
        default=True,
        description="Enable audio normalization"
    )
    target_dbfs: float = Field(
        default=-20.0,
        description="Target loudness in dBFS"
    )


class ProcessingSettings(BaseSettings):
    """General processing settings."""
    
    model_config = SettingsConfigDict(
        env_prefix="PROCESSING_",
        env_file=".env",
        extra="ignore"
    )
    
    max_file_size_mb: int = Field(
        default=500,
        description="Maximum input file size in MB"
    )
    timeout_seconds: int = Field(
        default=600,
        description="Processing timeout in seconds"
    )
    max_concurrent: int = Field(
        default=4,
        description="Maximum concurrent processing tasks"
    )
    retry_attempts: int = Field(
        default=3,
        description="Number of retry attempts on failure"
    )


class ServerSettings(BaseSettings):
    """HTTP server settings."""
    
    model_config = SettingsConfigDict(
        env_prefix="SERVER_",
        env_file=".env",
        extra="ignore"
    )
    
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    workers: int = Field(default=1)
    log_level: str = Field(default="info")


class AppSettings(BaseSettings):
    """Root application settings."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )
    
    # Application metadata
    app_name: str = Field(default="audio-preprocess")
    app_version: str = Field(default="2.0.0")
    environment: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    debug: bool = Field(default=False)
    
    # Processing mode
    processing_mode: Literal["queue", "polling", "manual"] = Field(
        default="queue",
        description="How to trigger processing: queue (recommended), polling, or manual (API only)"
    )
    polling_interval_seconds: int = Field(
        default=10,
        description="Interval for polling mode"
    )
    
    # Nested settings
    azure: AzureSettings = Field(default_factory=AzureSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    vad: VADSettings = Field(default_factory=VADSettings)
    silence: SilenceCompressionSettings = Field(default_factory=SilenceCompressionSettings)
    noise: NoiseReductionSettings = Field(default_factory=NoiseReductionSettings)
    normalize: NormalizationSettings = Field(default_factory=NormalizationSettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)


# Global settings instance
settings = AppSettings()
