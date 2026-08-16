from __future__ import annotations

import struct
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

PREAMBLE = b"\x55" * 8
SYNC_WORD = b"\xd3\x91\xc5\xa7"
PROTOCOL_VERSION = 1
FLAG_START = 0x01
FLAG_END = 0x02
HEADER = struct.Struct(">BBIIH")
CRC = struct.Struct(">I")
MAX_PAYLOAD_SIZE = 65_535


@dataclass(frozen=True, slots=True)
class Packet:
    flags: int
    stream_id: int
    sequence: int
    payload: bytes

    def to_bytes(self) -> bytes:
        header = HEADER.pack(
            PROTOCOL_VERSION,
            self.flags,
            self.stream_id,
            self.sequence,
            len(self.payload),
        )
        body = header + self.payload
        checksum = CRC.pack(zlib.crc32(body))
        return PREAMBLE + SYNC_WORD + body + checksum


@dataclass(frozen=True, slots=True)
class FrameDecodeResult:
    data: bytes | None
    packet_count: int
    crc_errors: int
    lost_packets: int
    protocol_errors: int

    @property
    def success(self) -> bool:
        return self.data is not None and self.lost_packets == 0


class FrameEncoder:
    def __init__(self, payload_size: int = 512) -> None:
        if not 1 <= payload_size <= MAX_PAYLOAD_SIZE:
            raise ValueError("payload_size must be in [1, 65535]")
        self.payload_size = payload_size

    def packets(self, data: bytes, *, stream_id: int | None = None) -> Iterator[Packet]:
        raw = bytes(data)
        identifier = zlib.crc32(raw) if stream_id is None else stream_id
        chunks = [raw[i : i + self.payload_size] for i in range(0, len(raw), self.payload_size)]
        if not chunks:
            chunks = [b""]
        last = len(chunks) - 1
        for sequence, payload in enumerate(chunks):
            flags = (FLAG_START if sequence == 0 else 0) | (FLAG_END if sequence == last else 0)
            yield Packet(flags, identifier, sequence, payload)

    def iter_bytes(self, data: bytes) -> Iterator[bytes]:
        for packet in self.packets(data):
            yield packet.to_bytes()

    def encode(self, data: bytes) -> bytes:
        return b"".join(self.iter_bytes(data))


class FrameStreamDecoder:
    """Incrementally finds and validates packets in a demodulated byte stream."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._packets: dict[int, dict[int, Packet]] = {}
        self.crc_errors = 0
        self.protocol_errors = 0

    def feed(self, data: bytes) -> None:
        self._buffer.extend(data)
        self._parse()

    def _parse(self) -> None:
        minimum = len(SYNC_WORD) + HEADER.size + CRC.size
        while True:
            sync_at = self._buffer.find(SYNC_WORD)
            if sync_at < 0:
                keep = len(SYNC_WORD) - 1
                if len(self._buffer) > keep:
                    del self._buffer[:-keep]
                return
            if sync_at:
                del self._buffer[:sync_at]
            if len(self._buffer) < minimum:
                return
            header_start = len(SYNC_WORD)
            header_end = header_start + HEADER.size
            version, flags, stream_id, sequence, payload_length = HEADER.unpack(
                self._buffer[header_start:header_end]
            )
            if version != PROTOCOL_VERSION or flags & ~(FLAG_START | FLAG_END):
                self.protocol_errors += 1
                del self._buffer[0]
                continue
            packet_end = header_end + payload_length + CRC.size
            if len(self._buffer) < packet_end:
                return
            body = bytes(self._buffer[header_start : packet_end - CRC.size])
            received_crc = CRC.unpack(self._buffer[packet_end - CRC.size : packet_end])[0]
            del self._buffer[:packet_end]
            if zlib.crc32(body) != received_crc:
                self.crc_errors += 1
                continue
            payload = body[HEADER.size:]
            packet = Packet(flags, stream_id, sequence, payload)
            self._packets.setdefault(stream_id, {}).setdefault(sequence, packet)

    def finish(self) -> FrameDecodeResult:
        self._parse()
        candidates: list[tuple[int, dict[int, Packet], int]] = []
        for stream_id, packets in self._packets.items():
            first = packets.get(0)
            if first is None or not first.flags & FLAG_START:
                continue
            end_sequences = [seq for seq, packet in packets.items() if packet.flags & FLAG_END]
            if end_sequences:
                candidates.append((stream_id, packets, min(end_sequences)))
        if not candidates:
            return FrameDecodeResult(None, 0, self.crc_errors, 0, self.protocol_errors)
        _, packets, end_sequence = max(candidates, key=lambda candidate: len(candidate[1]))
        missing = sum(sequence not in packets for sequence in range(end_sequence + 1))
        if missing:
            return FrameDecodeResult(
                None, len(packets), self.crc_errors, missing, self.protocol_errors
            )
        data = b"".join(packets[sequence].payload for sequence in range(end_sequence + 1))
        return FrameDecodeResult(
            data, end_sequence + 1, self.crc_errors, 0, self.protocol_errors
        )


def decode_chunks(chunks: Iterable[bytes]) -> FrameDecodeResult:
    decoder = FrameStreamDecoder()
    for chunk in chunks:
        decoder.feed(chunk)
    return decoder.finish()
