import zlib

import pytest

from kotone.file_payload import (
    FILE_HEADER,
    FilePayloadError,
    pack_file_payload,
    prepare_file_payload_source,
    try_unpack_file_payload,
    unpack_file_payload,
)


@pytest.mark.parametrize(
    ("filename", "data"),
    [
        ("message.bin", b""),
        ("資料-01.dat", bytes(range(256)) * 4),
    ],
)
def test_file_payload_round_trip(filename: str, data: bytes) -> None:
    packed = pack_file_payload(filename, data)
    restored = unpack_file_payload(packed)
    assert restored.filename == filename
    assert restored.data == data
    assert restored.crc32 == zlib.crc32(data)


def test_legacy_payload_is_not_misidentified() -> None:
    assert try_unpack_file_payload(b"legacy bytes") is None


@pytest.mark.parametrize(
    "filename",
    ["", ".", "..", "../secret", "folder/file.bin", r"folder\file.bin", "CON.txt", "bad?.bin", "tail. "],
)
def test_unsafe_filename_is_rejected(filename: str) -> None:
    with pytest.raises(FilePayloadError):
        pack_file_payload(filename, b"data")


def test_corrupt_file_content_is_rejected() -> None:
    packed = bytearray(pack_file_payload("data.bin", b"valid content"))
    packed[-1] ^= 1
    with pytest.raises(FilePayloadError, match="file CRC mismatch"):
        unpack_file_payload(packed)


def test_invalid_declared_size_is_rejected() -> None:
    packed = bytearray(pack_file_payload("data.bin", b"content"))
    file_size_offset = FILE_HEADER.size - 12
    packed[file_size_offset : file_size_offset + 8] = (999).to_bytes(8, "big")
    with pytest.raises(FilePayloadError, match="size"):
        unpack_file_payload(packed)


def test_packed_file_source_streams_full_payload_and_offsets(tmp_path) -> None:
    path = tmp_path / "資料.bin"
    data = bytes(range(256)) * 40
    path.write_bytes(data)
    expected = pack_file_payload(path.name, data)

    source = prepare_file_payload_source(path, chunk_size=257)

    assert source.total_size == len(expected)
    assert source.stream_id == zlib.crc32(expected)
    assert b"".join(source.iter_chunks(chunk_size=113)) == expected
    assert b"".join(source.iter_chunks(offset=4_096, chunk_size=113)) == expected[4_096:]
    assert source.crc32_prefix(4_096) == zlib.crc32(expected[:4_096])
