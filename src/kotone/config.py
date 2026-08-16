from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ModemProfile = Literal[
    "reliable",
    "fast",
    "a2dp",
    "a2dp-stereo",
    "a2dp-stereo-fec",
    "a2dp-ofdm-441",
    "a2dp-ofdm-328",
    "a2dp-ofdm-328-robust",
    "a2dp-ofdm",
]


@dataclass(frozen=True, slots=True)
class ModemConfig:
    """Physical-layer settings for the reference 4-FSK modem."""

    scheme: str = "4fsk"
    channel_count: int = 1
    fec_symbols: int = 0
    interleave: bool = False
    bits_per_symbol: int = 2
    parallel_symbols: int = 1
    sample_rate: int = 48_000
    symbol_rate: int = 1_200
    frequencies: tuple[float, ...] = (
        2_400.0,
        3_600.0,
        4_800.0,
        6_000.0,
    )
    amplitude: float = 0.8

    def __post_init__(self) -> None:
        if not self.scheme:
            raise ValueError("scheme must not be empty")
        if self.channel_count <= 0:
            raise ValueError("channel_count must be positive")
        if not 0 <= self.fec_symbols < 255:
            raise ValueError("fec_symbols must be in [0, 254]")
        if self.bits_per_symbol <= 0 or self.parallel_symbols <= 0:
            raise ValueError("symbol dimensions must be positive")
        if self.sample_rate % self.symbol_rate:
            raise ValueError("sample_rate must be divisible by symbol_rate")
        if self.scheme in {"4fsk", "stereo-4fsk"} and len(self.frequencies) != 4:
            raise ValueError("4-FSK requires exactly four frequencies")
        if (
            self.scheme == "stereo-ofdm-psk"
            and len(self.frequencies) != self.parallel_symbols
        ):
            raise ValueError("OFDM frequency count must match parallel_symbols")
        if not 0.0 < self.amplitude <= 1.0:
            raise ValueError("amplitude must be in (0, 1]")
        nyquist = self.sample_rate / 2
        if any(f <= 0 or f >= nyquist for f in self.frequencies):
            raise ValueError("frequencies must be between zero and Nyquist")

    @property
    def samples_per_symbol(self) -> int:
        return self.sample_rate // self.symbol_rate

    @property
    def raw_bitrate(self) -> int:
        return (
            self.symbol_rate
            * self.bits_per_symbol
            * self.parallel_symbols
            * self.channel_count
        )


@dataclass(frozen=True, slots=True)
class CodecConfig:
    packet_payload_size: int = 512
    modem: ModemConfig = ModemConfig()

    def __post_init__(self) -> None:
        if not 1 <= self.packet_payload_size <= 65_535:
            raise ValueError("packet_payload_size must be in [1, 65535]")


def modem_config_for_profile(profile: ModemProfile) -> ModemConfig:
    """Return one of Kotone's interoperable v0.1 modem profiles."""
    if profile == "reliable":
        return ModemConfig()
    if profile == "fast":
        # Ten samples per symbol and an integer number of cycles for every tone.
        # This keeps the simple correlator suitable for a future embedded decoder.
        return ModemConfig(
            symbol_rate=4_800,
            frequencies=(4_800.0, 9_600.0, 14_400.0, 19_200.0),
        )
    if profile == "a2dp":
        # Eight samples per symbol. Adjacent tones differ by one complete cycle
        # per symbol, and every tone returns to zero at the symbol boundary.
        # This profile is verified against 48 kHz / 328 kbit/s stereo SBC.
        return ModemConfig(
            symbol_rate=6_000,
            frequencies=(3_000.0, 9_000.0, 15_000.0, 21_000.0),
        )
    if profile == "a2dp-stereo":
        return ModemConfig(
            scheme="stereo-4fsk",
            channel_count=2,
            symbol_rate=4_800,
            frequencies=(2_400.0, 7_200.0, 12_000.0, 16_800.0),
        )
    if profile == "a2dp-stereo-fec":
        return ModemConfig(
            scheme="stereo-4fsk",
            channel_count=2,
            fec_symbols=8,
            interleave=True,
            symbol_rate=6_000,
            frequencies=(3_000.0, 8_000.0, 13_000.0, 18_000.0),
        )
    if profile == "a2dp-ofdm-441":
        # Native CD/A2DP rate: 42 samples per symbol and integer-cycle
        # carriers from 2.1 through 17.85 kHz.
        return ModemConfig(
            scheme="stereo-ofdm-psk",
            channel_count=2,
            fec_symbols=16,
            interleave=True,
            bits_per_symbol=2,
            parallel_symbols=16,
            sample_rate=44_100,
            symbol_rate=1_050,
            frequencies=tuple(float(value) for value in range(2_100, 17_851, 1_050)),
        )
    if profile == "a2dp-ofdm-328":
        return ModemConfig(
            scheme="stereo-ofdm-psk",
            channel_count=2,
            fec_symbols=16,
            interleave=True,
            bits_per_symbol=2,
            parallel_symbols=16,
            symbol_rate=1_000,
            frequencies=tuple(float(value) for value in range(2_000, 18_000, 1_000)),
        )
    if profile == "a2dp-ofdm-328-robust":
        return ModemConfig(
            scheme="stereo-ofdm-psk",
            channel_count=2,
            fec_symbols=32,
            interleave=True,
            bits_per_symbol=2,
            parallel_symbols=16,
            symbol_rate=1_000,
            frequencies=tuple(float(value) for value in range(2_000, 18_000, 1_000)),
        )
    if profile == "a2dp-ofdm":
        return ModemConfig(
            scheme="stereo-ofdm-psk",
            channel_count=2,
            fec_symbols=8,
            interleave=True,
            bits_per_symbol=3,
            parallel_symbols=16,
            symbol_rate=1_000,
            frequencies=tuple(float(value) for value in range(2_000, 18_000, 1_000)),
        )
    raise ValueError(f"unknown modem profile: {profile}")


def codec_config_for_profile(
    profile: ModemProfile, *, packet_payload_size: int | None = None
) -> CodecConfig:
    if packet_payload_size is None:
        if profile in {"a2dp-ofdm-441", "a2dp-ofdm-328", "a2dp-ofdm-328-robust"}:
            packet_payload_size = 4_096
        elif profile == "a2dp-ofdm":
            packet_payload_size = 1_024
        else:
            packet_payload_size = 512
    return CodecConfig(
        packet_payload_size=packet_payload_size,
        modem=modem_config_for_profile(profile),
    )
