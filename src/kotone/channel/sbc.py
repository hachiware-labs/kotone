from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray


def find_ffmpeg() -> str:
    """Find FFmpeg on PATH or in the optional imageio-ffmpeg package."""
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg
    except ImportError as error:
        raise RuntimeError(
            "SBC simulation requires FFmpeg; install it or run "
            "'uv sync --extra sbc'"
        ) from error
    return imageio_ffmpeg.get_ffmpeg_exe()


def sbc_round_trip(
    samples: ArrayLike,
    *,
    sample_rate: int = 48_000,
    bitrate: int = 328_000,
    flush_samples: int = 4_096,
    ffmpeg: str | None = None,
) -> NDArray[np.float32]:
    """Pass mono PCM through a stereo SBC encode/decode simulation.

    Mono is duplicated to both A2DP channels and mixed back after decoding.
    Stereo input preserves two independent channels. Trailing silence drains the
    SBC filters so the end of the final Kotone packet is retained.
    """
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if bitrate <= 0:
        raise ValueError("bitrate must be positive")
    if flush_samples < 0:
        raise ValueError("flush_samples must not be negative")

    values = np.asarray(samples, dtype=np.float32)
    if values.ndim == 1:
        source_channels = 1
    elif values.ndim == 2 and values.shape[1] == 2:
        source_channels = 2
    else:
        raise ValueError("SBC simulation requires mono or stereo PCM")
    if flush_samples:
        silence_shape = (flush_samples,) if source_channels == 1 else (flush_samples, 2)
        values = np.concatenate(
            (values, np.zeros(silence_shape, dtype=np.float32)), axis=0
        )
    pcm = np.rint(np.clip(values, -1.0, 1.0) * 32_767).astype("<i2")
    executable = ffmpeg or find_ffmpeg()

    with tempfile.TemporaryDirectory(prefix="kotone-sbc-") as temporary:
        root = Path(temporary)
        source_path = root / "source.wav"
        sbc_path = root / "channel.sbc"
        restored_path = root / "restored.wav"
        with wave.open(str(source_path), "wb") as output:
            output.setnchannels(source_channels)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(pcm.tobytes())

        encode_command = [
            executable,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source_path),
        ]
        if source_channels == 1:
            encode_command.extend(("-ac", "2"))
        encode_command.extend(("-c:a", "sbc", "-b:a", str(bitrate), str(sbc_path)))
        restored_channels = 1 if source_channels == 1 else 2
        commands = (
            encode_command,
            [
                executable,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(sbc_path),
                "-ac",
                str(restored_channels),
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                str(restored_path),
            ],
        )
        try:
            for command in commands:
                subprocess.run(command, check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as error:
            detail = getattr(error, "stderr", None) or str(error)
            raise RuntimeError(f"SBC simulation failed: {detail.strip()}") from error

        with wave.open(str(restored_path), "rb") as restored:
            frames = restored.readframes(restored.getnframes())
    result = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32_768.0
    if restored_channels == 2:
        return result.reshape(-1, 2)
    return result
