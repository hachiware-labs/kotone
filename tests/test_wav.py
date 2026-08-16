import hashlib
import os

from kotone.channel import decode_wav, encode_wav
from kotone.config import CodecConfig, modem_config_for_profile


def test_wav_round_trip(tmp_path) -> None:
    original = os.urandom(4_097)
    output = tmp_path / "encoded.wav"
    config = CodecConfig(packet_payload_size=300)
    encode_wav(original, output, config)
    restored = decode_wav(output, config)
    assert restored == original
    assert hashlib.sha256(restored).hexdigest() == hashlib.sha256(original).hexdigest()


def test_stereo_a2dp_wav_round_trip(tmp_path) -> None:
    original = os.urandom(4_097)
    output = tmp_path / "encoded-stereo.wav"
    config = CodecConfig(
        packet_payload_size=300,
        modem=modem_config_for_profile("a2dp-stereo"),
    )
    encode_wav(original, output, config)
    assert decode_wav(output, config) == original


def test_stereo_ofdm_wav_round_trip(tmp_path) -> None:
    original = os.urandom(4_097)
    output = tmp_path / "encoded-ofdm.wav"
    config = CodecConfig(
        packet_payload_size=1_024,
        modem=modem_config_for_profile("a2dp-ofdm"),
    )
    encode_wav(original, output, config)
    assert decode_wav(output, config) == original


def test_stereo_ofdm_441_wav_round_trip_with_startup_silence(tmp_path) -> None:
    original = os.urandom(4_097)
    output = tmp_path / "encoded-ofdm-441.wav"
    config = CodecConfig(
        packet_payload_size=1_024,
        modem=modem_config_for_profile("a2dp-ofdm-441"),
    )
    encode_wav(original, output, config, startup_silence_seconds=0.5)
    assert decode_wav(output, config) == original
