import wave

import numpy as np
import pytest

from kotone import codec_config_for_profile
from kotone.channel import add_awgn, add_noise_wav, decode_wav, encode_wav


def test_add_awgn_reaches_requested_snr() -> None:
    time = np.arange(48_000, dtype=np.float64) / 48_000
    signal = (0.2 * np.sin(2 * np.pi * 1_000 * time)).astype(np.float32)
    noisy = add_awgn(signal, snr_db=20.0, seed=42)
    noise = noisy - signal
    measured = 20 * np.log10(np.sqrt(np.mean(signal**2)) / np.sqrt(np.mean(noise**2)))
    assert measured == pytest.approx(20.0, abs=0.15)


def test_noise_wav_is_reproducible_and_preserves_stereo(tmp_path) -> None:
    config = codec_config_for_profile("a2dp-ofdm-328-robust")
    original = bytes(range(256)) * 8
    clean = tmp_path / "clean.wav"
    noisy_a = tmp_path / "noisy-a.wav"
    noisy_b = tmp_path / "noisy-b.wav"
    encode_wav(original, clean, config)
    result = add_noise_wav(clean, noisy_a, snr_db=30.0, seed=1234)
    add_noise_wav(clean, noisy_b, snr_db=30.0, seed=1234)
    assert noisy_a.read_bytes() == noisy_b.read_bytes()
    assert result.channels == 2
    with wave.open(str(noisy_a), "rb") as generated:
        assert generated.getnchannels() == 2
        assert generated.getframerate() == 48_000
    assert decode_wav(noisy_a, config) == original


def test_noise_wav_rejects_in_place_overwrite(tmp_path) -> None:
    path = tmp_path / "same.wav"
    path.write_bytes(b"not opened")
    with pytest.raises(ValueError, match="must differ"):
        add_noise_wav(path, path, snr_db=20.0)
