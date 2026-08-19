from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from kotone.config import CodecConfig
from kotone.fec import IdentityFEC
from kotone.framing import FrameDecodeResult, FrameEncoder, FrameStreamDecoder
from kotone.modem import create_modem
from kotone.modem.base import Modem


@dataclass(frozen=True, slots=True)
class DecodeReport:
    data: bytes | None
    packet_count: int
    crc_errors: int
    lost_packets: int
    protocol_errors: int
    fec_corrections: int = 0

    @property
    def success(self) -> bool:
        return self.data is not None

    @classmethod
    def from_frame(
        cls, result: FrameDecodeResult, *, fec_corrections: int = 0
    ) -> DecodeReport:
        return cls(
            result.data,
            result.packet_count,
            result.crc_errors,
            result.lost_packets,
            result.protocol_errors,
            fec_corrections,
        )


class DecodeError(ValueError):
    def __init__(self, message: str, report: DecodeReport) -> None:
        super().__init__(message)
        self.report = report


class Encoder:
    def __init__(
        self,
        config: CodecConfig | None = None,
        *,
        modem: Modem | None = None,
        fec: IdentityFEC | None = None,
    ) -> None:
        self.config = config or CodecConfig()
        self.modem = modem or create_modem(self.config.modem)
        self.fec = fec or IdentityFEC()
        self.framer = FrameEncoder(self.config.packet_payload_size)

    def iter_encode(
        self,
        data: bytes,
        *,
        stream_id: int | None = None,
        start_sequence: int = 0,
    ) -> Iterator[NDArray[np.float32]]:
        for framed_packet in self.framer.iter_bytes(
            bytes(data), stream_id=stream_id, start_sequence=start_sequence
        ):
            yield self.modem.modulate(self.fec.encode(framed_packet))

    def iter_encode_chunks(
        self,
        chunks: Iterable[bytes],
        *,
        total_size: int,
        stream_id: int,
        start_sequence: int = 0,
        source_offset: int = 0,
    ) -> Iterator[NDArray[np.float32]]:
        for framed_packet in self.framer.iter_chunk_bytes(
            chunks,
            total_size=total_size,
            stream_id=stream_id,
            start_sequence=start_sequence,
            source_offset=source_offset,
        ):
            yield self.modem.modulate(self.fec.encode(framed_packet))

    def push(self, data: bytes) -> NDArray[np.float32]:
        return self.encode(data)

    def encode(self, data: bytes) -> NDArray[np.float32]:
        chunks = list(self.iter_encode(data))
        return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)


class Decoder:
    """Symbol-aligned streaming decoder used by channel adapters."""

    def __init__(
        self,
        config: CodecConfig | None = None,
        *,
        modem: Modem | None = None,
        fec: IdentityFEC | None = None,
    ) -> None:
        self.config = config or CodecConfig()
        self.modem = modem or create_modem(self.config.modem)
        self.fec = fec or IdentityFEC()
        self._demodulator = self.modem.new_demodulator()
        self._frames = FrameStreamDecoder()

    def push(self, samples: ArrayLike) -> None:
        decoded = self._demodulator.push(samples)
        if decoded:
            self._frames.feed(self.fec.decode(decoded))

    def finish(self) -> DecodeReport:
        tail = self._demodulator.finish()
        if tail:
            self._frames.feed(self.fec.decode(tail))
        return DecodeReport.from_frame(
            self._frames.finish(),
            fec_corrections=getattr(self.modem, "corrected_symbols", 0),
        )


def encode(data: bytes, config: CodecConfig | None = None) -> NDArray[np.float32]:
    return Encoder(config).encode(data)


def decode_with_report(samples: ArrayLike, config: CodecConfig | None = None) -> DecodeReport:
    settings = config or CodecConfig()
    modem = create_modem(settings.modem)
    demodulated = modem.demodulate(samples)
    frames = FrameStreamDecoder()
    frames.feed(demodulated)
    return DecodeReport.from_frame(
        frames.finish(), fec_corrections=getattr(modem, "corrected_symbols", 0)
    )


def decode(samples: ArrayLike, config: CodecConfig | None = None) -> bytes:
    report = decode_with_report(samples, config)
    if report.data is None:
        raise DecodeError(
            "no complete valid Kotone stream was found "
            f"(crc_errors={report.crc_errors}, lost_packets={report.lost_packets})",
            report,
        )
    return report.data


def decode_chunks(chunks: Iterable[ArrayLike], config: CodecConfig | None = None) -> DecodeReport:
    decoder = Decoder(config)
    for chunk in chunks:
        decoder.push(chunk)
    return decoder.finish()
