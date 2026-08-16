from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from kotone.config import ModemConfig
from kotone.framing.packet import PREAMBLE, SYNC_WORD


def _bytes_to_symbols(data: bytes) -> NDArray[np.uint8]:
    values = np.frombuffer(data, dtype=np.uint8)
    if values.size == 0:
        return np.empty(0, dtype=np.uint8)
    return np.column_stack(
        ((values >> 6) & 3, (values >> 4) & 3, (values >> 2) & 3, values & 3)
    ).reshape(-1).astype(np.uint8, copy=False)


def _symbols_to_bytes(symbols: NDArray[np.uint8]) -> bytes:
    usable = symbols[: symbols.size - symbols.size % 4]
    if usable.size == 0:
        return b""
    groups = usable.reshape(-1, 4)
    values = (
        (groups[:, 0] << 6)
        | (groups[:, 1] << 4)
        | (groups[:, 2] << 2)
        | groups[:, 3]
    )
    return values.astype(np.uint8, copy=False).tobytes()


class FourFSKModem:
    """Coherent-duration 4-FSK reference modem with two bits per symbol."""

    def __init__(self, config: ModemConfig | None = None) -> None:
        self.config = config or ModemConfig()
        count = self.config.samples_per_symbol
        time = np.arange(count, dtype=np.float64) / self.config.sample_rate
        frequencies = np.asarray(self.config.frequencies, dtype=np.float64)[:, None]
        phase = 2 * np.pi * frequencies * time[None, :]
        self._tones = (self.config.amplitude * np.sin(phase)).astype(np.float32)
        self._sin_refs = np.sin(phase).astype(np.float32)
        self._cos_refs = np.cos(phase).astype(np.float32)

    def modulate(self, data: bytes) -> NDArray[np.float32]:
        symbols = _bytes_to_symbols(data)
        if symbols.size == 0:
            return np.empty(0, dtype=np.float32)
        return self._tones[symbols].reshape(-1)

    def new_demodulator(self) -> FourFSKDemodulator:
        return FourFSKDemodulator(self)

    def _demodulate_symbols(self, samples: NDArray[np.float32]) -> NDArray[np.uint8]:
        count = self.config.samples_per_symbol
        usable = samples[: samples.size - samples.size % count]
        if usable.size == 0:
            return np.empty(0, dtype=np.uint8)
        blocks = usable.reshape(-1, count)
        in_phase = blocks @ self._cos_refs.T
        quadrature = blocks @ self._sin_refs.T
        energy = in_phase * in_phase + quadrature * quadrature
        return np.argmax(energy, axis=1).astype(np.uint8)

    def _find_alignment(self, samples: NDArray[np.float32]) -> tuple[int, int]:
        """Find sample alignment from the preamble, tolerating channel distortion."""
        count = self.config.samples_per_symbol
        search = samples[: min(samples.size, count * 4 * 256)]
        expected = _bytes_to_symbols(PREAMBLE + SYNC_WORD)
        candidates: list[tuple[int, float, int]] = []
        for offset in range(count):
            usable = search[offset : search.size - (search.size - offset) % count]
            if usable.size < expected.size * count:
                continue
            blocks = usable.reshape(-1, count)
            in_phase = blocks @ self._cos_refs.T
            quadrature = blocks @ self._sin_refs.T
            energy = in_phase * in_phase + quadrature * quadrature
            symbols = np.argmax(energy, axis=1).astype(np.uint8)
            purity = np.max(energy, axis=1) / np.maximum(np.sum(energy, axis=1), 1e-12)
            windows = np.lib.stride_tricks.sliding_window_view(symbols, expected.size)
            errors = np.count_nonzero(windows != expected, axis=1)
            start = int(np.argmin(errors))
            mean_purity = float(np.mean(purity[start : start + expected.size]))
            candidates.append((int(errors[start]), -mean_purity, offset + start * count))
        if candidates:
            # Prefer the fewest preamble errors, then the purest symbol blocks and
            # earliest sample. CRC still rejects a false acquisition.
            _, _, aligned_offset = min(candidates)
            return aligned_offset, 0
        return 0, 0

    def demodulate(self, samples: ArrayLike) -> bytes:
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        offset, symbol_phase = self._find_alignment(values)
        symbols = self._demodulate_symbols(values[offset:])
        return _symbols_to_bytes(symbols[symbol_phase:])


class FourFSKDemodulator:
    """Streaming demodulator for symbol-aligned PCM chunks."""

    def __init__(self, modem: FourFSKModem) -> None:
        self.modem = modem
        self._samples = np.empty(0, dtype=np.float32)
        self._symbols = np.empty(0, dtype=np.uint8)

    def push(self, samples: ArrayLike) -> bytes:
        incoming = np.asarray(samples, dtype=np.float32).reshape(-1)
        if incoming.size:
            self._samples = np.concatenate((self._samples, incoming))
        count = self.modem.config.samples_per_symbol
        sample_count = self._samples.size - self._samples.size % count
        if sample_count:
            decoded = self.modem._demodulate_symbols(self._samples[:sample_count])
            self._samples = self._samples[sample_count:]
            self._symbols = np.concatenate((self._symbols, decoded))
        symbol_count = self._symbols.size - self._symbols.size % 4
        if not symbol_count:
            return b""
        result = _symbols_to_bytes(self._symbols[:symbol_count])
        self._symbols = self._symbols[symbol_count:]
        return result

    def finish(self) -> bytes:
        return self.push(np.empty(0, dtype=np.float32))
