from __future__ import annotations

from dataclasses import dataclass
import struct
import zlib


FILE_MAGIC = b"KTF1"
FILE_VERSION = 1
FILE_HEADER = struct.Struct(">4sBBHHHQI")
MAX_FILENAME_BYTES = 255
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_WINDOWS_INVALID = set('<>:"/\\|?*')


class FilePayloadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FilePayload:
    filename: str
    data: bytes
    crc32: int


def validate_filename(filename: str) -> str:
    if not isinstance(filename, str) or not filename:
        raise FilePayloadError("filename must not be empty")
    if filename in {".", ".."}:
        raise FilePayloadError("relative path components are not filenames")
    if filename[-1] in {" ", "."}:
        raise FilePayloadError("filename must not end with a space or dot")
    if any(ord(character) < 32 or character in _WINDOWS_INVALID for character in filename):
        raise FilePayloadError("filename contains a control or reserved character")
    encoded = filename.encode("utf-8")
    if len(encoded) > MAX_FILENAME_BYTES:
        raise FilePayloadError(
            f"UTF-8 filename exceeds {MAX_FILENAME_BYTES} bytes"
        )
    device_name = filename.split(".", 1)[0].upper()
    if device_name in _WINDOWS_RESERVED:
        raise FilePayloadError("filename is reserved on Windows")
    return filename


def pack_file_payload(filename: str, data: bytes) -> bytes:
    safe_name = validate_filename(filename)
    encoded_name = safe_name.encode("utf-8")
    content = bytes(data)
    header_length = FILE_HEADER.size + len(encoded_name)
    header = FILE_HEADER.pack(
        FILE_MAGIC,
        FILE_VERSION,
        0,
        header_length,
        len(encoded_name),
        0,
        len(content),
        zlib.crc32(content),
    )
    return header + encoded_name + content


def unpack_file_payload(payload: bytes) -> FilePayload:
    raw = bytes(payload)
    if len(raw) < FILE_HEADER.size:
        raise FilePayloadError("file payload header is incomplete")
    (
        magic,
        version,
        flags,
        header_length,
        filename_length,
        reserved,
        file_size,
        expected_crc,
    ) = FILE_HEADER.unpack_from(raw)
    if magic != FILE_MAGIC:
        raise FilePayloadError("file payload magic is not KTF1")
    if version != FILE_VERSION:
        raise FilePayloadError(f"unsupported file payload version: {version}")
    if flags != 0 or reserved != 0:
        raise FilePayloadError("file payload flags or reserved field is invalid")
    if not 1 <= filename_length <= MAX_FILENAME_BYTES:
        raise FilePayloadError("filename length is invalid")
    if header_length != FILE_HEADER.size + filename_length:
        raise FilePayloadError("file payload header length is invalid")
    if len(raw) != header_length + file_size:
        raise FilePayloadError("file payload size does not match its header")
    try:
        filename = raw[FILE_HEADER.size:header_length].decode("utf-8")
    except UnicodeDecodeError as error:
        raise FilePayloadError("filename is not valid UTF-8") from error
    validate_filename(filename)
    data = raw[header_length:]
    actual_crc = zlib.crc32(data)
    if actual_crc != expected_crc:
        raise FilePayloadError(
            f"file CRC mismatch: expected {expected_crc:08x}, got {actual_crc:08x}"
        )
    return FilePayload(filename, data, expected_crc)


def try_unpack_file_payload(payload: bytes) -> FilePayload | None:
    raw = bytes(payload)
    if not raw.startswith(FILE_MAGIC):
        return None
    return unpack_file_payload(raw)
