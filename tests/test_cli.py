import wave
import zlib

from kotone.channel.wav import decode_wav
from kotone.cli import main
from kotone.config import codec_config_for_profile
from kotone.file_payload import unpack_file_payload
from kotone.file_payload import pack_file_payload
from kotone.resume import ResumeState, write_resume_state
from kotone.sender import SendResult


def test_cli_encode_decode(tmp_path) -> None:
    original = tmp_path / "input.bin"
    audio = tmp_path / "encoded.wav"
    restored = tmp_path / "output.bin"
    original.write_bytes(bytes(range(256)))
    assert main(["encode", str(original), str(audio)]) == 0
    assert main(["decode", str(audio), str(restored)]) == 0
    assert restored.read_bytes() == original.read_bytes()


def test_cli_encode_embeds_filename_and_decode_can_restore_it(
    tmp_path, monkeypatch
) -> None:
    original = tmp_path / "資料.bin"
    audio = tmp_path / "encoded.wav"
    original.write_bytes(b"named Kotone payload")
    profile = ["--profile", "a2dp-ofdm-441"]
    assert main(["encode", str(original), str(audio), *profile]) == 0

    decoded = decode_wav(audio, codec_config_for_profile("a2dp-ofdm-441"))
    envelope = unpack_file_payload(decoded)
    assert envelope.filename == "資料.bin"
    assert envelope.data == original.read_bytes()

    restore_directory = tmp_path / "restored"
    restore_directory.mkdir()
    monkeypatch.chdir(restore_directory)
    assert main(["decode", str(audio), *profile]) == 0
    assert (restore_directory / "資料.bin").read_bytes() == original.read_bytes()


def test_cli_fast_profile_encode_decode(tmp_path) -> None:
    original = tmp_path / "input.bin"
    audio = tmp_path / "encoded.wav"
    restored = tmp_path / "output.bin"
    original.write_bytes(bytes(range(256)) * 4)
    assert main(["encode", str(original), str(audio), "--profile", "fast"]) == 0
    assert main(["decode", str(audio), str(restored), "--profile", "fast"]) == 0
    assert restored.read_bytes() == original.read_bytes()


def test_cli_stereo_profile_encode_decode(tmp_path) -> None:
    original = tmp_path / "input.bin"
    audio = tmp_path / "encoded-stereo.wav"
    restored = tmp_path / "output.bin"
    original.write_bytes(bytes(range(256)) * 4)
    profile = ["--profile", "a2dp-stereo"]
    assert main(["encode", str(original), str(audio), *profile]) == 0
    assert main(["decode", str(audio), str(restored), *profile]) == 0
    assert restored.read_bytes() == original.read_bytes()


def test_cli_ofdm_profile_encode_decode(tmp_path) -> None:
    original = tmp_path / "input.bin"
    audio = tmp_path / "encoded-ofdm.wav"
    restored = tmp_path / "output.bin"
    original.write_bytes(bytes(range(256)) * 8)
    profile = ["--profile", "a2dp-ofdm"]
    assert main(["encode", str(original), str(audio), *profile]) == 0
    assert main(["decode", str(audio), str(restored), *profile]) == 0
    assert restored.read_bytes() == original.read_bytes()


def test_cli_ofdm_441_profile_adds_a2dp_startup_guard(tmp_path) -> None:
    original = tmp_path / "input.bin"
    audio = tmp_path / "encoded-ofdm-441.wav"
    restored = tmp_path / "output.bin"
    original.write_bytes(bytes(range(256)) * 4)
    profile = ["--profile", "a2dp-ofdm-441"]
    assert main(["encode", str(original), str(audio), *profile]) == 0
    with wave.open(str(audio), "rb") as generated:
        assert generated.getframerate() == 44_100
        assert generated.readframes(22_050) == bytes(22_050 * 2 * 2)
    assert main(["decode", str(audio), str(restored), *profile]) == 0
    assert restored.read_bytes() == original.read_bytes()


def test_cli_demo_creates_listening_samples(tmp_path) -> None:
    original = tmp_path / "input.bin"
    output_dir = tmp_path / "sounds"
    original.write_bytes(bytes(range(256)))
    profiles = ["reliable", "a2dp-ofdm-328-robust", "a2dp-ofdm"]
    assert (
        main(
            [
                "demo",
                str(original),
                str(output_dir),
                "--duration",
                "0.1",
                "--profiles",
                *profiles,
            ]
        )
        == 0
    )
    outputs = sorted(output_dir.glob("*.wav"))
    assert len(outputs) == 3
    with wave.open(str(outputs[0]), "rb") as reliable:
        assert reliable.getnchannels() == 1
    with wave.open(str(outputs[-1]), "rb") as ofdm:
        assert ofdm.getnchannels() == 2


def test_cli_encode_noise_decode_pipeline(tmp_path) -> None:
    original = tmp_path / "input.bin"
    clean = tmp_path / "clean.wav"
    noisy = tmp_path / "noisy.wav"
    restored = tmp_path / "output.bin"
    original.write_bytes(bytes(range(256)) * 4)
    profile = ["--profile", "a2dp-ofdm-328-robust"]
    assert main(["encode", str(original), str(clean), *profile]) == 0
    assert (
        main(
            [
                "noise",
                str(clean),
                str(noisy),
                "--snr-db",
                "30",
                "--seed",
                "42",
            ]
        )
        == 0
    )
    assert main(["decode", str(noisy), str(restored), *profile]) == 0
    assert restored.read_bytes() == original.read_bytes()


def test_cli_encode_resume_validates_and_forwards_position(
    tmp_path, monkeypatch
) -> None:
    original = tmp_path / "resume.bin"
    output = tmp_path / "resume.wav"
    original.write_bytes(bytes(range(256)) * 40)
    payload = pack_file_payload(original.name, original.read_bytes())
    packet_size = 4_096
    accepted = packet_size
    state = ResumeState(
        "00A3F",
        zlib.crc32(payload),
        1,
        accepted,
        zlib.crc32(payload[:accepted]),
        packet_size,
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    write_resume_state(state)
    call = {}

    def fake_encode_wav(data, path, config, **kwargs):
        call.update(data=data, path=path, config=config, kwargs=kwargs)

    monkeypatch.setattr("kotone.cli.encode_wav", fake_encode_wav)
    assert (
        main(
            [
                "encode",
                str(original),
                str(output),
                "--profile",
                "a2dp-ofdm-441",
                "--resume",
                "00A3F",
            ]
        )
        == 0
    )
    assert call["data"] == payload
    assert call["kwargs"]["stream_id"] == state.stream_id
    assert call["kwargs"]["start_sequence"] == 1


def test_cli_send_uses_a2dp_profile_and_default_speaker(tmp_path, monkeypatch) -> None:
    original = tmp_path / "send.bin"
    original.write_bytes(b"Kotone")
    call = {}

    def fake_send_file(path, config, **kwargs):
        call.update(path=path, config=config, kwargs=kwargs)
        return SendResult("Windows default speaker", 0x12345678, 0, 1, 32)

    monkeypatch.setattr("kotone.cli.send_file", fake_send_file)

    assert main(["send", str(original)]) == 0
    assert call["path"] == original
    assert call["config"].modem.sample_rate == 44_100
    assert call["config"].packet_payload_size == 4_096
    assert call["kwargs"] == {
        "device": None,
        "startup_silence_seconds": 0.5,
        "tail_silence_seconds": 1.0,
        "resume_id": None,
    }


def test_cli_send_forwards_resume_id(tmp_path, monkeypatch) -> None:
    original = tmp_path / "send.bin"
    original.write_bytes(b"Kotone")
    call = {}

    def fake_send_file(path, config, **kwargs):
        call.update(kwargs)
        return SendResult("speaker", 1, 1, 2, 4_100)

    monkeypatch.setattr("kotone.cli.send_file", fake_send_file)

    assert main(["send", str(original), "--resume", "00A3F"]) == 0
    assert call["resume_id"] == "00A3F"


def test_cli_send_reports_non_windows_error(tmp_path, monkeypatch, capsys) -> None:
    original = tmp_path / "send.bin"
    original.write_bytes(b"Kotone")

    def unsupported(*args, **kwargs):
        raise RuntimeError(
            "kotone send is supported only on Windows (WaveOut is required)"
        )

    monkeypatch.setattr("kotone.cli.send_file", unsupported)

    assert main(["send", str(original)]) == 2
    assert "supported only on Windows" in capsys.readouterr().err
