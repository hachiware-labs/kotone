from __future__ import annotations

from dataclasses import dataclass
import re
import struct
import zlib


TOKEN_VERSION = "KTR1"
_TOKEN_BODY = struct.Struct(">4sIIQI")
_TOKEN_PATTERN = re.compile(
    r"^KTR1-([0-9A-Fa-f]{8})-([0-9A-Fa-f]{8})-"
    r"([0-9A-Fa-f]{16})-([0-9A-Fa-f]{8})-([0-9A-Fa-f]{8})$"
)


@dataclass(frozen=True, slots=True)
class ResumeToken:
    stream_id: int
    next_sequence: int
    accepted_bytes: int
    stream_crc: int

    def encode(self) -> str:
        body = _TOKEN_BODY.pack(
            TOKEN_VERSION.encode("ascii"),
            self.stream_id,
            self.next_sequence,
            self.accepted_bytes,
            self.stream_crc,
        )
        checksum = zlib.crc32(body)
        return (
            f"{TOKEN_VERSION}-{self.stream_id:08X}-{self.next_sequence:08X}-"
            f"{self.accepted_bytes:016X}-{self.stream_crc:08X}-{checksum:08X}"
        )

    @classmethod
    def parse(cls, value: str) -> ResumeToken:
        match = _TOKEN_PATTERN.fullmatch(value.strip())
        if match is None:
            raise ValueError("resume token has an invalid format")
        stream_id, next_sequence, accepted_bytes, stream_crc, checksum = (
            int(field, 16) for field in match.groups()
        )
        body = _TOKEN_BODY.pack(
            TOKEN_VERSION.encode("ascii"),
            stream_id,
            next_sequence,
            accepted_bytes,
            stream_crc,
        )
        calculated = zlib.crc32(body)
        if checksum != calculated:
            raise ValueError(
                "resume token CRC mismatch: "
                f"expected {checksum:08X}, calculated {calculated:08X}"
            )
        return cls(stream_id, next_sequence, accepted_bytes, stream_crc)


def validate_resume_data(
    token: ResumeToken,
    data: bytes,
    *,
    packet_payload_size: int,
) -> None:
    raw = bytes(data)
    stream_id = zlib.crc32(raw)
    if token.stream_id != stream_id:
        raise ValueError(
            "resume token belongs to a different payload: "
            f"token={token.stream_id:08X}, payload={stream_id:08X}"
        )
    packet_count = max(1, (len(raw) + packet_payload_size - 1) // packet_payload_size)
    if token.next_sequence >= packet_count:
        raise ValueError(
            f"resume packet {token.next_sequence} is outside {packet_count} packets"
        )
    expected_bytes = min(token.next_sequence * packet_payload_size, len(raw))
    if token.accepted_bytes != expected_bytes:
        raise ValueError(
            "resume token byte position does not match packet size: "
            f"token={token.accepted_bytes}, expected={expected_bytes}"
        )
    calculated_crc = zlib.crc32(raw[:expected_bytes])
    if token.stream_crc != calculated_crc:
        raise ValueError(
            "resume token prefix CRC does not match the payload: "
            f"token={token.stream_crc:08X}, payload={calculated_crc:08X}"
        )
