import hashlib
import os

import numpy as np
import pytest

from kotone import (
    CodecConfig,
    available_modems,
    codec_config_for_profile,
    decode,
    encode,
)


@pytest.mark.parametrize("size", [0, 1, 31, 512, 2_049])
def test_digital_loopback(size: int) -> None:
    original = os.urandom(size)
    samples = encode(original, CodecConfig(packet_payload_size=256))
    restored = decode(samples, CodecConfig(packet_payload_size=256))
    assert restored == original
    assert hashlib.sha256(restored).digest() == hashlib.sha256(original).digest()


def test_decoder_finds_signal_after_unaligned_leading_samples() -> None:
    original = os.urandom(100)
    signal = encode(original)
    samples = np.concatenate((np.zeros(17, dtype=np.float32), signal))
    assert decode(samples) == original


def test_fast_profile_reaches_nearly_ten_kilobits_per_second() -> None:
    config = codec_config_for_profile("fast")
    original = os.urandom(2_049)
    assert config.modem.raw_bitrate == 9_600
    assert decode(encode(original, config), config) == original


def test_a2dp_profile_reaches_twelve_kilobits_per_second_after_delay() -> None:
    config = codec_config_for_profile("a2dp")
    original = os.urandom(2_049)
    signal = encode(original, config)
    delayed = np.concatenate(
        (
            np.zeros(74, dtype=np.float32),
            signal,
            np.zeros(256, dtype=np.float32),
        )
    )
    assert config.modem.raw_bitrate == 12_000
    assert decode(delayed, config) == original


def test_stereo_a2dp_profile_round_trip() -> None:
    config = codec_config_for_profile("a2dp-stereo")
    original = os.urandom(4_097)
    signal = encode(original, config)
    delayed = np.concatenate(
        (
            np.zeros((74, 2), dtype=np.float32),
            signal,
            np.zeros((256, 2), dtype=np.float32),
        ),
        axis=0,
    )
    assert config.modem.raw_bitrate == 19_200
    assert signal.ndim == 2 and signal.shape[1] == 2
    assert decode(delayed, config) == original
    assert {"4fsk", "stereo-4fsk"}.issubset(available_modems())


def test_stereo_fec_profile_round_trip() -> None:
    config = codec_config_for_profile("a2dp-stereo-fec")
    original = os.urandom(8_193)
    assert config.modem.raw_bitrate == 24_000
    assert config.modem.fec_symbols == 8
    assert config.modem.interleave
    assert decode(encode(original, config), config) == original


def test_stereo_ofdm_profile_round_trip() -> None:
    config = codec_config_for_profile("a2dp-ofdm")
    original = os.urandom(8_193)
    signal = encode(original, config)
    assert config.packet_payload_size == 1_024
    assert config.modem.raw_bitrate == 96_000
    assert signal.ndim == 2 and signal.shape[1] == 2
    assert decode(signal, config) == original
    delayed = np.concatenate(
        (np.zeros((24_000, 2), dtype=np.float32), signal), axis=0
    )
    assert decode(delayed, config) == original


def test_stereo_qpsk_ofdm_328_profile_round_trip() -> None:
    config = codec_config_for_profile("a2dp-ofdm-328")
    original = os.urandom(16_385)
    assert config.packet_payload_size == 4_096
    assert config.modem.bits_per_symbol == 2
    assert config.modem.raw_bitrate == 64_000
    assert decode(encode(original, config), config) == original


def test_stereo_qpsk_ofdm_441_profile_round_trip() -> None:
    config = codec_config_for_profile("a2dp-ofdm-441")
    original = os.urandom(8_193)
    assert config.packet_payload_size == 4_096
    assert config.modem.sample_rate == 44_100
    assert config.modem.samples_per_symbol == 42
    assert config.modem.raw_bitrate == 67_200
    assert decode(encode(original, config), config) == original


def test_stereo_qpsk_ofdm_328_robust_profile_round_trip() -> None:
    config = codec_config_for_profile("a2dp-ofdm-328-robust")
    original = os.urandom(16_385)
    assert config.packet_payload_size == 4_096
    assert config.modem.fec_symbols == 32
    assert config.modem.raw_bitrate == 64_000
    assert decode(encode(original, config), config) == original
