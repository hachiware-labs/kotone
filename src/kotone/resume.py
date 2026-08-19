from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re


RESUME_STATE_VERSION = 1
_RESUME_ID_PATTERN = re.compile(r"^[0-9A-Fa-f]{5}$")


def normalize_resume_id(value: str) -> str:
    candidate = value.strip()
    if _RESUME_ID_PATTERN.fullmatch(candidate) is None:
        raise ValueError("resume ID must be exactly five hexadecimal digits")
    return candidate.upper()


def default_resume_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Kotone" / "resume"
    return Path.home() / ".local" / "state" / "kotone" / "resume"


@dataclass(frozen=True, slots=True)
class ResumeState:
    resume_id: str
    stream_id: int
    next_sequence: int
    accepted_bytes: int
    stream_crc: int
    packet_payload_size: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "resume_id", normalize_resume_id(self.resume_id))
        if not 0 <= self.stream_id <= 0xFFFFFFFF:
            raise ValueError("stream_id must fit in 32 bits")
        if not 0 <= self.next_sequence <= 0xFFFFFFFF:
            raise ValueError("next_sequence must fit in 32 bits")
        if not 0 <= self.accepted_bytes <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("accepted_bytes must fit in 64 bits")
        if not 0 <= self.stream_crc <= 0xFFFFFFFF:
            raise ValueError("stream_crc must fit in 32 bits")
        if not 1 <= self.packet_payload_size <= 65_535:
            raise ValueError("packet_payload_size must be in [1, 65535]")
        expected_bytes = self.next_sequence * self.packet_payload_size
        if self.accepted_bytes != expected_bytes:
            raise ValueError(
                "resume state byte position does not match packet size: "
                f"state={self.accepted_bytes}, expected={expected_bytes}"
            )

    def as_dict(self) -> dict[str, int | str]:
        return {
            "version": RESUME_STATE_VERSION,
            "resume_id": self.resume_id,
            "stream_id": self.stream_id,
            "next_sequence": self.next_sequence,
            "accepted_bytes": self.accepted_bytes,
            "stream_crc": self.stream_crc,
            "packet_payload_size": self.packet_payload_size,
        }

    @classmethod
    def from_dict(cls, value: object) -> ResumeState:
        if not isinstance(value, dict) or value.get("version") != RESUME_STATE_VERSION:
            raise ValueError("resume state has an unsupported version")
        expected_keys = {
            "version",
            "resume_id",
            "stream_id",
            "next_sequence",
            "accepted_bytes",
            "stream_crc",
            "packet_payload_size",
        }
        if set(value) != expected_keys:
            raise ValueError("resume state fields are invalid")
        try:
            return cls(
                str(value["resume_id"]),
                int(value["stream_id"]),
                int(value["next_sequence"]),
                int(value["accepted_bytes"]),
                int(value["stream_crc"]),
                int(value["packet_payload_size"]),
            )
        except (TypeError, ValueError) as error:
            raise ValueError("resume state values are invalid") from error


def resume_state_path(
    resume_id: str, *, directory: str | Path | None = None
) -> Path:
    normalized = normalize_resume_id(resume_id)
    root = Path(directory) if directory is not None else default_resume_directory()
    return root / f"{normalized}.json"


def load_resume_state(
    resume_id: str, *, directory: str | Path | None = None
) -> ResumeState:
    normalized = normalize_resume_id(resume_id)
    path = resume_state_path(normalized, directory=directory)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"resume ID {normalized} was not found") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"resume state {normalized} could not be read") from error
    state = ResumeState.from_dict(raw)
    if state.resume_id != normalized:
        raise ValueError("resume state ID does not match its filename")
    return state


def write_resume_state(
    state: ResumeState, *, directory: str | Path | None = None
) -> Path:
    path = resume_state_path(state.resume_id, directory=directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(state.as_dict(), output, ensure_ascii=True, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def validate_resume_state(
    state: ResumeState,
    *,
    stream_id: int,
    total_size: int,
    packet_payload_size: int,
    prefix_crc: int,
) -> None:
    if total_size < 0:
        raise ValueError("total_size must not be negative")
    if packet_payload_size <= 0:
        raise ValueError("packet_payload_size must be positive")
    if state.stream_id != stream_id:
        raise ValueError(
            "resume ID belongs to a different payload: "
            f"state={state.stream_id:08X}, payload={stream_id:08X}"
        )
    if state.packet_payload_size != packet_payload_size:
        raise ValueError(
            "resume packet size does not match the selected profile: "
            f"state={state.packet_payload_size}, selected={packet_payload_size}"
        )
    packet_count = max(1, (total_size + packet_payload_size - 1) // packet_payload_size)
    if state.next_sequence >= packet_count:
        raise ValueError(
            f"resume packet {state.next_sequence} is outside {packet_count} packets"
        )
    if state.stream_crc != prefix_crc:
        raise ValueError(
            "resume state prefix CRC does not match the payload: "
            f"state={state.stream_crc:08X}, payload={prefix_crc:08X}"
        )
