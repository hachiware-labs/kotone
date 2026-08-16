import os

import pytest

pytest.importorskip("imageio_ffmpeg")

from kotone import codec_config_for_profile, decode, encode
from kotone.channel import sbc_round_trip


def test_a2dp_profile_survives_328_kbit_s_sbc() -> None:
    config = codec_config_for_profile("a2dp")
    original = os.urandom(4_097)
    restored_pcm = sbc_round_trip(
        encode(original, config),
        sample_rate=config.modem.sample_rate,
        bitrate=328_000,
    )
    assert decode(restored_pcm, config) == original


def test_stereo_a2dp_profile_survives_328_kbit_s_sbc() -> None:
    config = codec_config_for_profile("a2dp-stereo")
    original = os.urandom(16_385)
    restored_pcm = sbc_round_trip(
        encode(original, config),
        sample_rate=config.modem.sample_rate,
        bitrate=328_000,
    )
    assert decode(restored_pcm, config) == original


def test_stereo_fec_profile_survives_328_kbit_s_sbc() -> None:
    config = codec_config_for_profile("a2dp-stereo-fec")
    original = os.urandom(32_769)
    restored_pcm = sbc_round_trip(
        encode(original, config),
        sample_rate=config.modem.sample_rate,
        bitrate=328_000,
    )
    assert decode(restored_pcm, config) == original


def test_stereo_ofdm_profile_survives_512_kbit_s_sbc() -> None:
    config = codec_config_for_profile("a2dp-ofdm")
    original = os.urandom(32_769)
    restored_pcm = sbc_round_trip(
        encode(original, config),
        sample_rate=config.modem.sample_rate,
        bitrate=512_000,
    )
    assert decode(restored_pcm, config) == original


def test_stereo_qpsk_ofdm_profile_survives_328_kbit_s_sbc() -> None:
    config = codec_config_for_profile("a2dp-ofdm-328")
    original = os.urandom(32_769)
    restored_pcm = sbc_round_trip(
        encode(original, config),
        sample_rate=config.modem.sample_rate,
        bitrate=328_000,
    )
    assert decode(restored_pcm, config) == original


def test_stereo_qpsk_ofdm_441_profile_survives_328_kbit_s_sbc() -> None:
    config = codec_config_for_profile("a2dp-ofdm-441")
    original = os.urandom(8_193)
    restored_pcm = sbc_round_trip(
        encode(original, config),
        sample_rate=config.modem.sample_rate,
        bitrate=328_000,
    )
    assert decode(restored_pcm, config) == original


def test_stereo_qpsk_ofdm_robust_profile_survives_328_kbit_s_sbc() -> None:
    config = codec_config_for_profile("a2dp-ofdm-328-robust")
    original = os.urandom(32_769)
    restored_pcm = sbc_round_trip(
        encode(original, config),
        sample_rate=config.modem.sample_rate,
        bitrate=328_000,
    )
    assert decode(restored_pcm, config) == original
