import os

from kotone.framing import FrameEncoder, FrameStreamDecoder
from kotone.framing.packet import FLAG_END, FLAG_START


def test_frames_round_trip_incrementally() -> None:
    original = os.urandom(1_537)
    framed = FrameEncoder(payload_size=128).encode(original)
    decoder = FrameStreamDecoder()
    for offset in range(0, len(framed), 37):
        decoder.feed(framed[offset : offset + 37])
    result = decoder.finish()
    assert result.success
    assert result.data == original
    assert result.packet_count == 13
    assert result.crc_errors == 0


def test_crc_corruption_is_detected() -> None:
    framed = bytearray(FrameEncoder(payload_size=512).encode(b"important payload"))
    framed[-5] ^= 0x80
    decoder = FrameStreamDecoder()
    decoder.feed(framed)
    result = decoder.finish()
    assert not result.success
    assert result.data is None
    assert result.crc_errors == 1


def test_empty_payload_round_trip() -> None:
    decoder = FrameStreamDecoder()
    decoder.feed(FrameEncoder().encode(b""))
    result = decoder.finish()
    assert result.success
    assert result.data == b""


def test_resume_packets_keep_original_sequence_and_stream() -> None:
    data = bytes(range(256)) * 20
    encoder = FrameEncoder(payload_size=1_024)
    packets = list(
        encoder.packets(data, stream_id=0x54D87381, start_sequence=3)
    )
    assert packets[0].stream_id == 0x54D87381
    assert packets[0].sequence == 3
    assert not packets[0].flags & FLAG_START
    assert packets[-1].flags & FLAG_END
