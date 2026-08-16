from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray

from kotone.codec import decode_with_report, encode
from kotone.config import CodecConfig


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    channel: str
    payload_bytes: int
    audio_seconds: float
    payload_goodput_bps: float
    raw_bitrate_bps: int
    bit_error_rate: float
    packet_error_rate: float
    crc_errors: int
    lost_packets: int
    packet_count: int
    fec_corrections: int
    decode_success_rate: float
    encoding_seconds: float
    decoding_seconds: float
    success: bool

    def as_dict(self) -> dict[str, str | int | float | bool]:
        return asdict(self)


def _bit_errors(expected: bytes, actual: bytes | None) -> int:
    if actual is None:
        return len(expected) * 8
    common = min(len(expected), len(actual))
    errors = sum((left ^ right).bit_count() for left, right in zip(expected[:common], actual[:common]))
    return errors + abs(len(expected) - len(actual)) * 8


def benchmark(
    data: bytes,
    config: CodecConfig | None = None,
    *,
    channel: Callable[[NDArray[np.float32]], NDArray[np.float32]] | None = None,
    channel_name: str = "digital",
) -> BenchmarkResult:
    settings = config or CodecConfig()
    started = time.perf_counter()
    samples = encode(data, settings)
    encoding_seconds = time.perf_counter() - started
    received = channel(samples) if channel is not None else samples
    started = time.perf_counter()
    report = decode_with_report(received, settings)
    decoding_seconds = time.perf_counter() - started
    audio_seconds = samples.shape[0] / settings.modem.sample_rate
    total_bits = max(1, len(data) * 8)
    errors = _bit_errors(data, report.data)
    packet_errors = report.crc_errors + report.lost_packets
    observed_packets = report.packet_count + packet_errors
    success = report.data == data
    return BenchmarkResult(
        channel=channel_name,
        payload_bytes=len(data),
        audio_seconds=audio_seconds,
        payload_goodput_bps=len(data) / audio_seconds if audio_seconds else 0.0,
        raw_bitrate_bps=settings.modem.raw_bitrate,
        bit_error_rate=errors / total_bits,
        packet_error_rate=packet_errors / observed_packets if observed_packets else 0.0,
        crc_errors=report.crc_errors,
        lost_packets=report.lost_packets,
        packet_count=report.packet_count,
        fec_corrections=report.fec_corrections,
        decode_success_rate=1.0 if success else 0.0,
        encoding_seconds=encoding_seconds,
        decoding_seconds=decoding_seconds,
        success=success,
    )
