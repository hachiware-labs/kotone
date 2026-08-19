import zlib

import numpy as np
import pytest

import kotone.sender as sender
from kotone.channel import waveout
from kotone.config import codec_config_for_profile
from kotone.file_payload import pack_file_payload


def test_send_file_accepts_five_digit_pc_resume_fixture_and_streams_tail(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "pc-resume.bin"
    path.write_bytes(bytes(range(256)) * 40)
    packed = pack_file_payload(path.name, path.read_bytes())
    resume_directory = tmp_path / "resume"
    resume_directory.mkdir()
    # Fixed JSON contract shared with atom-lite-kotone's PC receiver.
    (resume_directory / "00A3F.json").write_text(
        '{"version":1,"resume_id":"00A3F","stream_id":973746768,'
        '"next_sequence":1,"accepted_bytes":4096,'
        '"stream_crc":852783039,"packet_payload_size":4096}\n',
        encoding="utf-8",
    )
    accepted = 4_096
    assert zlib.crc32(packed) == 0x3A0A3250
    assert zlib.crc32(packed[:accepted]) == 0x32D46FBF
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
        resume_id="00A3F",
        resume_directory=resume_directory,
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
