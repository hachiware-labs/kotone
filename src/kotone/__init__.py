"""Kotone: binary data over PCM audio."""

from kotone.codec import DecodeError, Decoder, DecodeReport, Encoder, decode, encode
from kotone.config import (
    CodecConfig,
    ModemConfig,
    ModemProfile,
    codec_config_for_profile,
    modem_config_for_profile,
)
from kotone.file_payload import (
    FilePayload,
    FilePayloadError,
    pack_file_payload,
    try_unpack_file_payload,
    unpack_file_payload,
)
from kotone.modem import available_modems, register_modem

__all__ = [
    "CodecConfig",
    "DecodeError",
    "DecodeReport",
    "Decoder",
    "Encoder",
    "FilePayload",
    "FilePayloadError",
    "ModemConfig",
    "ModemProfile",
    "available_modems",
    "codec_config_for_profile",
    "decode",
    "encode",
    "modem_config_for_profile",
    "pack_file_payload",
    "register_modem",
    "try_unpack_file_payload",
    "unpack_file_payload",
]

__version__ = "0.1.0"
