from __future__ import annotations

from collections.abc import Iterable
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import sys
import time


MMSYSERR_NOERROR = 0
WAVE_MAPPER = 0xFFFFFFFF
WAVE_FORMAT_PCM = 1
WHDR_DONE = 0x00000001


class WaveOutError(RuntimeError):
    pass


class WAVEOUTCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * 32),
        ("dwFormats", wintypes.DWORD),
        ("wChannels", wintypes.WORD),
        ("wReserved1", wintypes.WORD),
        ("dwSupport", wintypes.DWORD),
    ]


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", wintypes.DWORD),
        ("dwLoops", wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


def ensure_waveout_supported() -> None:
    if sys.platform != "win32":
        raise WaveOutError(
            "kotone send is supported only on Windows (WaveOut is required)"
        )


class CtypesWaveOutAPI:
    def __init__(self) -> None:
        ensure_waveout_supported()
        self.winmm = ctypes.WinDLL("winmm")
        self.winmm.waveOutGetNumDevs.restype = wintypes.UINT
        self.winmm.waveOutGetDevCapsW.argtypes = [
            ctypes.c_size_t,
            ctypes.POINTER(WAVEOUTCAPSW),
            wintypes.UINT,
        ]
        self.winmm.waveOutOpen.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.UINT,
            ctypes.POINTER(WAVEFORMATEX),
            ctypes.c_size_t,
            ctypes.c_size_t,
            wintypes.DWORD,
        ]
        header_args = [
            ctypes.c_void_p,
            ctypes.POINTER(WAVEHDR),
            wintypes.UINT,
        ]
        self.winmm.waveOutPrepareHeader.argtypes = header_args
        self.winmm.waveOutWrite.argtypes = header_args
        self.winmm.waveOutUnprepareHeader.argtypes = header_args
        self.winmm.waveOutReset.argtypes = [ctypes.c_void_p]
        self.winmm.waveOutClose.argtypes = [ctypes.c_void_p]

    @staticmethod
    def _check(result: int, operation: str) -> None:
        if result != MMSYSERR_NOERROR:
            raise WaveOutError(f"{operation} failed with MMRESULT {result}")

    def resolve_device(self, name_fragment: str | None) -> tuple[int, str]:
        if name_fragment is None:
            return WAVE_MAPPER, "Windows default speaker"
        try:
            device_id = int(name_fragment, 10)
        except ValueError:
            device_id = -1
        if device_id >= 0:
            return device_id, f"WaveOut device {device_id}"

        names: list[str] = []
        for candidate in range(self.winmm.waveOutGetNumDevs()):
            caps = WAVEOUTCAPSW()
            result = self.winmm.waveOutGetDevCapsW(
                candidate, ctypes.byref(caps), ctypes.sizeof(caps)
            )
            if result == MMSYSERR_NOERROR:
                names.append(caps.szPname)
                if name_fragment.casefold() in caps.szPname.casefold():
                    return candidate, caps.szPname
        raise WaveOutError(
            f"WaveOut device containing {name_fragment!r} was not found; "
            f"devices={names}"
        )

    def open(self, device_id: int, wave_format: WAVEFORMATEX):
        handle = ctypes.c_void_p()
        self._check(
            self.winmm.waveOutOpen(
                ctypes.byref(handle),
                device_id,
                ctypes.byref(wave_format),
                0,
                0,
                0,
            ),
            "waveOutOpen",
        )
        return handle

    def prepare(self, handle, header: WAVEHDR) -> None:
        self._check(
            self.winmm.waveOutPrepareHeader(
                handle, ctypes.byref(header), ctypes.sizeof(header)
            ),
            "waveOutPrepareHeader",
        )

    def write(self, handle, header: WAVEHDR) -> None:
        self._check(
            self.winmm.waveOutWrite(
                handle, ctypes.byref(header), ctypes.sizeof(header)
            ),
            "waveOutWrite",
        )

    def reset(self, handle) -> None:
        self._check(self.winmm.waveOutReset(handle), "waveOutReset")

    def unprepare(self, handle, header: WAVEHDR) -> None:
        self._check(
            self.winmm.waveOutUnprepareHeader(
                handle, ctypes.byref(header), ctypes.sizeof(header)
            ),
            "waveOutUnprepareHeader",
        )

    def close(self, handle) -> None:
        self._check(self.winmm.waveOutClose(handle), "waveOutClose")


@dataclass(slots=True)
class _QueuedBuffer:
    buffer: ctypes.Array
    header: WAVEHDR


class WaveOutPlayer:
    def __init__(
        self,
        *,
        api=None,
        queue_depth: int = 4,
        poll_interval: float = 0.005,
        sleep=time.sleep,
    ) -> None:
        if queue_depth <= 0:
            raise ValueError("queue_depth must be positive")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.api = api or CtypesWaveOutAPI()
        self.queue_depth = queue_depth
        self.poll_interval = poll_interval
        self.sleep = sleep

    def play(
        self,
        pcm_chunks: Iterable[bytes],
        *,
        sample_rate: int,
        channels: int,
        device: str | None = None,
    ) -> str:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if channels <= 0:
            raise ValueError("channels must be positive")
        device_id, device_name = self.api.resolve_device(device)
        block_align = channels * 2
        wave_format = WAVEFORMATEX(
            WAVE_FORMAT_PCM,
            channels,
            sample_rate,
            sample_rate * block_align,
            block_align,
            16,
            0,
        )
        handle = self.api.open(device_id, wave_format)
        queued: list[_QueuedBuffer] = []
        active_error: BaseException | None = None

        def reap(*, wait: bool) -> None:
            while queued:
                if not queued[0].header.dwFlags & WHDR_DONE:
                    if not wait:
                        return
                    self.sleep(self.poll_interval)
                    continue
                item = queued[0]
                self.api.unprepare(handle, item.header)
                queued.pop(0)

        try:
            for pcm in pcm_chunks:
                raw = bytes(pcm)
                if not raw:
                    continue
                if len(raw) % block_align:
                    raise ValueError("PCM chunk is not aligned to complete frames")
                while len(queued) >= self.queue_depth:
                    reap(wait=True)
                buffer = ctypes.create_string_buffer(raw)
                header = WAVEHDR(
                    ctypes.addressof(buffer), len(raw), 0, 0, 0, 0, None, 0
                )
                item = _QueuedBuffer(buffer, header)
                self.api.prepare(handle, header)
                queued.append(item)
                self.api.write(handle, header)
                reap(wait=False)
            while queued:
                reap(wait=True)
        except BaseException as error:
            active_error = error
            raise
        finally:
            cleanup_error: BaseException | None = None
            try:
                self.api.reset(handle)
            except BaseException as error:
                cleanup_error = error
            for item in queued:
                try:
                    self.api.unprepare(handle, item.header)
                except BaseException as error:
                    cleanup_error = cleanup_error or error
            try:
                self.api.close(handle)
            except BaseException as error:
                cleanup_error = cleanup_error or error
            if active_error is None and cleanup_error is not None:
                raise cleanup_error
        return device_name


def play_pcm16(
    pcm_chunks: Iterable[bytes],
    *,
    sample_rate: int,
    channels: int,
    device: str | None = None,
) -> str:
    ensure_waveout_supported()
    return WaveOutPlayer().play(
        pcm_chunks,
        sample_rate=sample_rate,
        channels=channels,
        device=device,
    )
