from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from kotone.codec import DecodeError, Decoder, DecodeReport, Encoder
from kotone.config import CodecConfig

PathLike = str | Path


def encode_wav(
    data: bytes,
    path: PathLike,
    config: CodecConfig | None = None,
    *,
    startup_silence_seconds: float = 0.0,
    stream_id: int | None = None,
    start_sequence: int = 0,
) -> None:
    settings = config or CodecConfig()
    if startup_silence_seconds < 0:
        raise ValueError("startup_silence_seconds must not be negative")
    encoder = Encoder(settings)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(settings.modem.channel_count)
        output.setsampwidth(2)
        output.setframerate(settings.modem.sample_rate)
        silence_frames = round(
            startup_silence_seconds * settings.modem.sample_rate
        )
        silence_chunk_frames = 65_536
        silence_chunk = bytes(
            silence_chunk_frames * settings.modem.channel_count * 2
        )
        while silence_frames:
            frame_count = min(silence_frames, silence_chunk_frames)
            output.writeframesraw(
                silence_chunk[: frame_count * settings.modem.channel_count * 2]
            )
            silence_frames -= frame_count
        for samples in encoder.iter_encode(
            data, stream_id=stream_id, start_sequence=start_sequence
        ):
            pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32_767).astype("<i2")
            output.writeframesraw(pcm.tobytes())


def decode_wav_with_report(
    path: PathLike, config: CodecConfig | None = None, *, chunk_frames: int = 65_536
) -> DecodeReport:
    settings = config or CodecConfig()
    decoder = Decoder(settings)
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != settings.modem.channel_count:
            raise ValueError(
                f"expected {settings.modem.channel_count}-channel WAV, "
                f"got {source.getnchannels()} channels"
            )
        if source.getsampwidth() != 2:
            raise ValueError("Kotone v0.1 requires signed 16-bit WAV input")
        if source.getframerate() != settings.modem.sample_rate:
            raise ValueError(
                f"expected {settings.modem.sample_rate} Hz WAV, got {source.getframerate()} Hz"
            )
        while frames := source.readframes(chunk_frames):
            samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32_768.0
            if settings.modem.channel_count > 1:
                samples = samples.reshape(-1, settings.modem.channel_count)
            decoder.push(samples)
    return decoder.finish()


def decode_wav(path: PathLike, config: CodecConfig | None = None) -> bytes:
    report = decode_wav_with_report(path, config)
    if report.data is None:
        raise DecodeError(
            "WAV did not contain a complete valid Kotone stream "
            f"(crc_errors={report.crc_errors}, lost_packets={report.lost_packets})",
            report,
        )
    return report.data
