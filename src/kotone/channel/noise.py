from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray

PathLike = str | Path


@dataclass(frozen=True, slots=True)
class NoiseResult:
    frames: int
    channels: int
    sample_rate: int
    snr_db: float
    signal_rms: float
    noise_rms: float
    clipped_samples: int


def _noise_rms(signal_rms: float, snr_db: float) -> float:
    if not math.isfinite(snr_db):
        raise ValueError("snr_db must be finite")
    return signal_rms / (10.0 ** (snr_db / 20.0))


def add_awgn(
    samples: ArrayLike, *, snr_db: float, seed: int | None = None
) -> NDArray[np.float32]:
    """Add white Gaussian noise at an RMS signal-to-noise ratio."""
    values = np.asarray(samples, dtype=np.float32)
    signal_rms = float(np.sqrt(np.mean(values.astype(np.float64) ** 2)))
    noise_rms = _noise_rms(signal_rms, snr_db)
    random = np.random.default_rng(seed)
    noise = random.normal(0.0, noise_rms, size=values.shape)
    return np.clip(values + noise, -1.0, 1.0).astype(np.float32)


def add_noise_wav(
    input_path: PathLike,
    output_path: PathLike,
    *,
    snr_db: float,
    seed: int | None = None,
    chunk_frames: int = 65_536,
) -> NoiseResult:
    """Add reproducible AWGN to a signed 16-bit PCM WAV without loading it all."""
    source_path = Path(input_path)
    destination_path = Path(output_path)
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("input and output WAV paths must differ")
    if chunk_frames <= 0:
        raise ValueError("chunk_frames must be positive")

    squared_sum = 0.0
    sample_count = 0
    with wave.open(str(source_path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError("noise currently requires signed 16-bit PCM WAV")
        channels = source.getnchannels()
        sample_rate = source.getframerate()
        frame_count = source.getnframes()
        while frames := source.readframes(chunk_frames):
            values = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32_768.0
            squared_sum += float(values @ values)
            sample_count += values.size

    signal_rms = math.sqrt(squared_sum / sample_count) if sample_count else 0.0
    noise_rms = _noise_rms(signal_rms, snr_db)
    random = np.random.default_rng(seed)
    clipped_samples = 0
    upper_limit = 32_767 / 32_768

    with wave.open(str(source_path), "rb") as source, wave.open(
        str(destination_path), "wb"
    ) as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        while frames := source.readframes(chunk_frames):
            values = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32_768.0
            noise = random.normal(0.0, noise_rms, size=values.shape)
            noisy = values + noise
            clipped_samples += int(
                np.count_nonzero((noisy < -1.0) | (noisy > upper_limit))
            )
            pcm = np.rint(np.clip(noisy, -1.0, upper_limit) * 32_768).astype("<i2")
            output.writeframesraw(pcm.tobytes())

    return NoiseResult(
        frames=frame_count,
        channels=channels,
        sample_rate=sample_rate,
        snr_db=snr_db,
        signal_rms=signal_rms,
        noise_rms=noise_rms,
        clipped_samples=clipped_samples,
    )
