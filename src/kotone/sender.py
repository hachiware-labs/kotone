from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from kotone.channel.waveout import ensure_waveout_supported, play_pcm16
from kotone.codec import Encoder
from kotone.config import CodecConfig
from kotone.file_payload import prepare_file_payload_source
from kotone.resume import load_resume_state, validate_resume_state


@dataclass(frozen=True, slots=True)
class SendResult:
    device_name: str
    stream_id: int
    first_sequence: int
    packet_count: int
    payload_bytes: int


def _silence_chunks(
    seconds: float,
    *,
    sample_rate: int,
    channels: int,
    chunk_frames: int = 65_536,
) -> Iterator[bytes]:
    if seconds < 0:
        raise ValueError("silence duration must not be negative")
    frames = round(seconds * sample_rate)
    while frames:
        count = min(frames, chunk_frames)
        yield bytes(count * channels * 2)
        frames -= count


def _pcm16_chunks(
    encoded_chunks,
    *,
    sample_rate: int,
    channels: int,
    startup_silence_seconds: float,
    tail_silence_seconds: float,
) -> Iterator[bytes]:
    yield from _silence_chunks(
        startup_silence_seconds,
        sample_rate=sample_rate,
        channels=channels,
    )
    for samples in encoded_chunks:
        pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32_767).astype("<i2")
        yield pcm.tobytes()
    yield from _silence_chunks(
        tail_silence_seconds,
        sample_rate=sample_rate,
        channels=channels,
    )


def send_file(
    path: str | Path,
    config: CodecConfig,
    *,
    device: str | None = None,
    startup_silence_seconds: float = 0.5,
    tail_silence_seconds: float = 1.0,
    resume_id: str | None = None,
    resume_directory: str | Path | None = None,
) -> SendResult:
    ensure_waveout_supported()
    if startup_silence_seconds < 0:
        raise ValueError("startup silence must not be negative")
    if tail_silence_seconds < 0:
        raise ValueError("tail silence must not be negative")

    source = prepare_file_payload_source(path)
    resume = (
        load_resume_state(resume_id, directory=resume_directory)
        if resume_id is not None
        else None
    )
    first_sequence = 0
    source_offset = 0
    if resume is not None:
        expected_offset = min(
            resume.next_sequence * config.packet_payload_size,
            source.total_size,
        )
        validate_resume_state(
            resume,
            stream_id=source.stream_id,
            total_size=source.total_size,
            packet_payload_size=config.packet_payload_size,
            prefix_crc=source.crc32_prefix(expected_offset),
        )
        first_sequence = resume.next_sequence
        source_offset = resume.accepted_bytes

    packet_count = max(
        1,
        (source.total_size + config.packet_payload_size - 1)
        // config.packet_payload_size,
    )
    encoder = Encoder(config)
    encoded = encoder.iter_encode_chunks(
        source.iter_chunks(offset=source_offset),
        total_size=source.total_size,
        stream_id=source.stream_id,
        start_sequence=first_sequence,
        source_offset=source_offset,
    )
    pcm = _pcm16_chunks(
        encoded,
        sample_rate=config.modem.sample_rate,
        channels=config.modem.channel_count,
        startup_silence_seconds=startup_silence_seconds,
        tail_silence_seconds=tail_silence_seconds,
    )
    device_name = play_pcm16(
        pcm,
        sample_rate=config.modem.sample_rate,
        channels=config.modem.channel_count,
        device=device,
    )
    return SendResult(
        device_name,
        source.stream_id,
        first_sequence,
        packet_count,
        source.total_size,
    )
