from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
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


@dataclass(frozen=True, slots=True)
class PackedFileSource:
    """Re-openable, bounded-memory source for a KTF1-wrapped file."""

    path: Path
    prefix: bytes
    file_size: int
    stream_id: int

    @property
    def total_size(self) -> int:
        return len(self.prefix) + self.file_size

    def iter_chunks(
        self, *, offset: int = 0, chunk_size: int = 65_536
    ) -> Iterator[bytes]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not 0 <= offset <= self.total_size:
            raise ValueError(f"offset must be in [0, {self.total_size}]")

        file_offset = 0
        if offset < len(self.prefix):
            yield self.prefix[offset:]
        else:
            file_offset = offset - len(self.prefix)

        remaining = self.file_size - file_offset
        with self.path.open("rb") as source:
            if file_offset:
                source.seek(file_offset)
            while remaining:
                chunk = source.read(min(chunk_size, remaining))
                if not chunk:
                    raise OSError(
                        f"input file changed while sending: {self.path}"
                    )
                remaining -= len(chunk)
                yield chunk
            if source.read(1):
                raise OSError(f"input file changed while sending: {self.path}")

    def crc32_prefix(self, length: int) -> int:
        if not 0 <= length <= self.total_size:
            raise ValueError(f"prefix length must be in [0, {self.total_size}]")
        checksum = 0
        remaining = length
        for chunk in self.iter_chunks():
            if not remaining:
                break
            part = chunk[:remaining]
            checksum = zlib.crc32(part, checksum)
            remaining -= len(part)
        if remaining:
            raise OSError(f"input file changed while validating: {self.path}")
        return checksum


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
    content = bytes(data)
    prefix = file_payload_prefix(filename, len(content), zlib.crc32(content))
    return prefix + content


def file_payload_prefix(filename: str, file_size: int, file_crc32: int) -> bytes:
    safe_name = validate_filename(filename)
    encoded_name = safe_name.encode("utf-8")
    header_length = FILE_HEADER.size + len(encoded_name)
    header = FILE_HEADER.pack(
        FILE_MAGIC,
        FILE_VERSION,
        0,
        header_length,
        len(encoded_name),
        0,
        file_size,
        file_crc32,
    )
    return header + encoded_name


def prepare_file_payload_source(
    path: str | Path, *, chunk_size: int = 65_536
) -> PackedFileSource:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    input_path = Path(path)
    file_crc = 0
    file_size = 0
    with input_path.open("rb") as source:
        while chunk := source.read(chunk_size):
            file_crc = zlib.crc32(chunk, file_crc)
            file_size += len(chunk)

    prefix = file_payload_prefix(input_path.name, file_size, file_crc)
    stream_id = zlib.crc32(prefix)
    verified_file_crc = 0
    with input_path.open("rb") as source:
        remaining = file_size
        while remaining:
            chunk = source.read(min(chunk_size, remaining))
            if not chunk:
                raise OSError(f"input file changed while preparing: {input_path}")
            stream_id = zlib.crc32(chunk, stream_id)
            verified_file_crc = zlib.crc32(chunk, verified_file_crc)
            remaining -= len(chunk)
        if source.read(1):
            raise OSError(f"input file changed while preparing: {input_path}")
    if verified_file_crc != file_crc:
        raise OSError(f"input file changed while preparing: {input_path}")
    return PackedFileSource(input_path, prefix, file_size, stream_id)


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
