import pytest

from kotone.channel.waveout import (
    CtypesWaveOutAPI,
    WHDR_DONE,
    WAVE_MAPPER,
    WaveOutError,
    WaveOutPlayer,
)


class FakeWaveOutAPI:
    def __init__(self, *, fail_write: bool = False, auto_done: bool = True) -> None:
        self.fail_write = fail_write
        self.auto_done = auto_done
        self.calls = []
        self.headers = []

    def resolve_device(self, device):
        self.calls.append(("resolve", device))
        return WAVE_MAPPER, "Windows default speaker"

    def open(self, device_id, wave_format):
        self.calls.append(("open", device_id, wave_format.nSamplesPerSec))
        return object()

    def prepare(self, handle, header):
        self.calls.append(("prepare", header.dwBufferLength))
        self.headers.append(header)

    def write(self, handle, header):
        self.calls.append(("write", header.dwBufferLength))
        if self.fail_write:
            raise WaveOutError("test write failure")
        if self.auto_done:
            header.dwFlags |= WHDR_DONE

    def reset(self, handle):
        self.calls.append(("reset",))
        for header in self.headers:
            header.dwFlags |= WHDR_DONE

    def unprepare(self, handle, header):
        self.calls.append(("unprepare", header.dwBufferLength))

    def close(self, handle):
        self.calls.append(("close",))


def test_ctypes_api_uses_wave_mapper_when_device_is_omitted() -> None:
    api = object.__new__(CtypesWaveOutAPI)
    assert api.resolve_device(None) == (WAVE_MAPPER, "Windows default speaker")


def test_waveout_queues_pcm_to_default_speaker_and_waits() -> None:
    api = FakeWaveOutAPI(auto_done=False)
    waits = []

    def finish_queued_buffers(seconds):
        waits.append(seconds)
        for header in api.headers:
            header.dwFlags |= WHDR_DONE

    player = WaveOutPlayer(api=api, queue_depth=2, sleep=finish_queued_buffers)

    device_name = player.play(
        [b"\x00" * 16, b"\x01" * 24],
        sample_rate=44_100,
        channels=2,
    )

    assert device_name == "Windows default speaker"
    assert api.calls[0] == ("resolve", None)
    assert ("open", WAVE_MAPPER, 44_100) in api.calls
    assert [call for call in api.calls if call[0] == "write"] == [
        ("write", 16),
        ("write", 24),
    ]
    assert waits
    assert api.calls[-2:] == [("reset",), ("close",)]


def test_waveout_resets_and_unprepares_after_playback_error() -> None:
    api = FakeWaveOutAPI(fail_write=True)
    player = WaveOutPlayer(api=api, sleep=lambda _: None)

    with pytest.raises(WaveOutError, match="write failure"):
        player.play([b"\x00" * 16], sample_rate=44_100, channels=2)

    assert ("reset",) in api.calls
    assert ("unprepare", 16) in api.calls
    assert api.calls[-1] == ("close",)
