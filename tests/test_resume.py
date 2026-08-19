import zlib

import pytest

from kotone.resume import ResumeToken, validate_resume_data


def test_resume_token_round_trip() -> None:
    token = ResumeToken(0x54D87381, 256, 1_048_576, 0x30E14955)
    assert ResumeToken.parse(token.encode()) == token


def test_resume_token_detects_corruption() -> None:
    encoded = ResumeToken(1, 2, 3, 4).encode()
    replacement = "0" if encoded[-1] != "0" else "1"
    with pytest.raises(ValueError, match="CRC mismatch"):
        ResumeToken.parse(encoded[:-1] + replacement)


def test_resume_data_validation() -> None:
    data = bytes(range(256)) * 20
    accepted = 4_096
    token = ResumeToken(
        zlib.crc32(data),
        1,
        accepted,
        zlib.crc32(data[:accepted]),
    )
    validate_resume_data(token, data, packet_payload_size=4_096)


def test_resume_data_rejects_different_payload() -> None:
    data = b"original payload"
    token = ResumeToken(zlib.crc32(data), 0, 0, 0)
    with pytest.raises(ValueError, match="different payload"):
        validate_resume_data(token, b"changed payload", packet_payload_size=4)
