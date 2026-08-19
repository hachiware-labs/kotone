import zlib

import numpy as np
import pytest

import kotone.sender as sender
from kotone.channel import waveout
from kotone.config import codec_config_for_profile
from kotone.file_payload import pack_file_payload
from kotone.resume import ResumeToken


def test_send_file_accepts_atom_pc_resume_fixture_and_streams_tail(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "pc-resume.bin"
    path.write_bytes(bytes(range(256)) * 40)
    packed = pack_file_payload(path.name, path.read_bytes())
    # Fixed KTR1 fixture using atom-lite-kotone Capture-Kotone.py's
    # >4sIIQI body and trailing CRC32 format.
    encoded_token = (
        "KTR1-3A0A3250-00000001-0000000000001000-32D46FBF-5EB013AB"
    )
    token = ResumeToken.parse(encoded_token)
    accepted = 4_096
    assert token == ResumeToken(0x3A0A3250, 1, accepted, 0x32D46FBF)
    assert zlib.crc32(packed) == token.stream_id
    assert zlib.crc32(packed[:accepted]) == token.stream_crc
    call = {}

    class FakeEncoder:
        def __init__(self, config):
            call["config"] = config

        def iter_encode_chunks(self, chunks, **kwargs):
            call["payload_tail"] = b"".join(chunks)
            call["encode_kwargs"] = kwargs
            yield np.zeros((2, 2), dtype=np.float32)

    def fake_play(pcm_chunks, **kwargs):
        call["pcm"] = list(pcm_chunks)
        call["play_kwargs"] = kwargs
        return "Default test speaker"

    monkeypatch.setattr(sender, "ensure_waveout_supported", lambda: None)
    monkeypatch.setattr(sender, "Encoder", FakeEncoder)
    monkeypatch.setattr(sender, "play_pcm16", fake_play)

    result = sender.send_file(
        path,
        codec_config_for_profile("a2dp-ofdm-441"),
        resume_token=encoded_token,
        startup_silence_seconds=0.01,
        tail_silence_seconds=0.02,
    )

    assert call["payload_tail"] == packed[accepted:]
    assert call["encode_kwargs"]["stream_id"] == 0x3A0A3250
    assert call["encode_kwargs"]["start_sequence"] == 1
    assert call["encode_kwargs"]["source_offset"] == accepted
    assert call["play_kwargs"]["device"] is None
    assert call["pcm"][0] == bytes(round(0.01 * 44_100) * 2 * 2)
    assert call["pcm"][-1] == bytes(round(0.02 * 44_100) * 2 * 2)
    assert result.first_sequence == 1
    assert result.stream_id == 0x3A0A3250
    assert result.device_name == "Default test speaker"


def test_send_file_reports_non_windows_support_error(monkeypatch) -> None:
    monkeypatch.setattr(waveout.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="only on Windows"):
        sender.send_file(
            "unused.bin",
            codec_config_for_profile("a2dp-ofdm-441"),
        )
