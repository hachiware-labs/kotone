import zlib

import pytest

from kotone.resume import (
    ResumeState,
    load_resume_state,
    normalize_resume_id,
    validate_resume_state,
    write_resume_state,
)


def test_resume_id_is_five_uppercase_hex_digits() -> None:
    assert normalize_resume_id("00a3f") == "00A3F"
    for invalid in ("A3F", "000000", "XYZ12", "00G3F"):
        with pytest.raises(ValueError, match="five hexadecimal"):
            normalize_resume_id(invalid)


def test_resume_state_round_trip(tmp_path) -> None:
    state = ResumeState("00a3f", 0x54D87381, 1, 4_096, 0x30E14955, 4_096)
    path = write_resume_state(state, directory=tmp_path)

    assert path.name == "00A3F.json"
    assert load_resume_state("00a3f", directory=tmp_path) == state


def test_missing_resume_id_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="00A3F was not found"):
        load_resume_state("00A3F", directory=tmp_path)


def test_resume_state_validation() -> None:
    data = bytes(range(256)) * 20
    accepted = 4_096
    state = ResumeState(
        "00001",
        zlib.crc32(data),
        1,
        accepted,
        zlib.crc32(data[:accepted]),
        4_096,
    )
    validate_resume_state(
        state,
        stream_id=zlib.crc32(data),
        total_size=len(data),
        packet_payload_size=4_096,
        prefix_crc=zlib.crc32(data[:accepted]),
    )


def test_resume_state_rejects_different_payload() -> None:
    data = b"original payload"
    state = ResumeState("00001", zlib.crc32(data), 0, 0, 0, 4)
    with pytest.raises(ValueError, match="different payload"):
        validate_resume_state(
            state,
            stream_id=zlib.crc32(b"changed payload"),
            total_size=len(data),
            packet_payload_size=4,
            prefix_crc=0,
        )


def test_resume_state_rejects_different_packet_size() -> None:
    state = ResumeState("00001", 1, 1, 4_096, 2, 4_096)
    with pytest.raises(ValueError, match="packet size"):
        validate_resume_state(
            state,
            stream_id=1,
            total_size=8_192,
            packet_payload_size=1_024,
            prefix_crc=2,
        )
