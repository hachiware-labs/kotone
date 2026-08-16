from __future__ import annotations

import math
import struct
import zlib

import numpy as np
from numpy.typing import ArrayLike, NDArray

from kotone.config import ModemConfig
from kotone.fec import ReedSolomonFEC

_PHY_HEADER = struct.Struct(">IH")
_PHY_CRC = struct.Struct(">I")
_LANE_LENGTH = struct.Struct(">H")
_ACQUISITION_BLOCKS = 4
_SYNC_BLOCKS = 2
_HEADER_REPETITIONS = 3
_MAX_STARTUP_SECONDS = 2


def _bytes_to_symbols(data: bytes, bits_per_symbol: int) -> NDArray[np.uint8]:
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
    if remainder := bits.size % bits_per_symbol:
        bits = np.pad(bits, (0, bits_per_symbol - remainder))
    weights = 1 << np.arange(bits_per_symbol - 1, -1, -1)
    return (bits.reshape(-1, bits_per_symbol) @ weights).astype(np.uint8)


def _symbols_to_bytes(
    symbols: NDArray[np.uint8], length: int, bits_per_symbol: int
) -> bytes:
    shifts = np.arange(bits_per_symbol - 1, -1, -1)
    bits = ((symbols[:, None] >> shifts) & 1).astype(np.uint8).reshape(-1)
    return np.packbits(bits).tobytes()[:length]


class StereoOFDMPSKModem:
    """Coherent stereo M-PSK OFDM modem for high-bitrate SBC channels."""

    def __init__(self, config: ModemConfig) -> None:
        if config.channel_count != 2:
            raise ValueError("stereo-ofdm-psk requires channel_count=2")
        if config.bits_per_symbol not in (2, 3):
            raise ValueError("stereo-ofdm-psk supports QPSK and 8-PSK")
        self.config = config
        self._modulation_order = 1 << config.bits_per_symbol
        self._phase_step = 2 * np.pi / self._modulation_order
        self._count = config.samples_per_symbol
        time = np.arange(self._count, dtype=np.float64) / config.sample_rate
        frequencies = np.asarray(config.frequencies, dtype=np.float64)[:, None]
        self._basis = np.exp(2j * np.pi * frequencies * time[None, :])
        self._amplitude = config.amplitude / config.parallel_symbols
        self._bytes_per_block = (
            config.parallel_symbols * config.bits_per_symbol // 8
        )
        if config.parallel_symbols * config.bits_per_symbol % 8:
            raise ValueError("OFDM block bit count must be byte-aligned")
        self._header_blocks = math.ceil(_PHY_HEADER.size / self._bytes_per_block)
        random = np.random.default_rng(0x4B6F746F)
        self._acquisition_symbols = random.integers(
            0,
            self._modulation_order,
            (_ACQUISITION_BLOCKS, config.parallel_symbols),
            dtype=np.uint8,
        )
        self._acquisition_coefficients = np.exp(
            1j * self._acquisition_symbols * self._phase_step
        )
        self._acquisition_wave = self._coefficients_to_pcm(
            self._acquisition_coefficients
        )
        self._acquisition_template = self._acquisition_wave.reshape(-1)
        self._sync_symbols = random.integers(
            0,
            self._modulation_order,
            (_SYNC_BLOCKS, config.parallel_symbols),
            dtype=np.uint8,
        )
        self._sync_coefficients = np.exp(
            1j * self._sync_symbols * self._phase_step
        )
        self._sync_wave = self._coefficients_to_pcm(self._sync_coefficients)
        self._fec = ReedSolomonFEC(
            config.fec_symbols or 8, interleave=config.interleave
        )
        self._tx_sequence = 0

    @property
    def corrected_symbols(self) -> int:
        return self._fec.corrected_symbols

    def _coefficients_to_pcm(
        self, coefficients: NDArray[np.complexfloating]
    ) -> NDArray[np.float32]:
        waves = self._amplitude * np.real(
            np.sum(coefficients[:, :, None] * self._basis[None, :, :], axis=1)
        )
        return waves.astype(np.float32)

    def _encode_blocks(self, data: bytes) -> NDArray[np.float32]:
        symbols = _bytes_to_symbols(data, self.config.bits_per_symbol)
        remainder = symbols.size % self.config.parallel_symbols
        if remainder:
            symbols = np.pad(symbols, (0, self.config.parallel_symbols - remainder))
        coefficients = np.exp(
            1j
            * symbols.reshape(-1, self.config.parallel_symbols)
            * self._phase_step
        )
        return self._coefficients_to_pcm(coefficients)

    def _lane_wave(self, sequence: int, data: bytes, padded_size: int) -> NDArray[np.float32]:
        lane_payload = _LANE_LENGTH.pack(len(data)) + data.ljust(padded_size, b"\x00")
        protected = self._fec.encode(lane_payload)
        header = _PHY_HEADER.pack(sequence, len(protected))
        checksum = _PHY_CRC.pack(zlib.crc32(header + lane_payload))
        header_wave = self._encode_blocks(header)
        data_wave = self._encode_blocks(protected + checksum)
        sync_wave = self._acquisition_wave if sequence == 0 else self._sync_wave
        return np.concatenate(
            (
                sync_wave,
                np.tile(header_wave, (_HEADER_REPETITIONS, 1)),
                data_wave,
            ),
            axis=0,
        ).reshape(-1)

    def modulate(self, data: bytes) -> NDArray[np.float32]:
        raw = bytes(data)
        sequence = self._tx_sequence
        self._tx_sequence += 1
        left_data = raw[::2]
        right_data = raw[1::2]
        padded_size = max(len(left_data), len(right_data))
        left = self._lane_wave(sequence, left_data, padded_size)
        right = self._lane_wave(sequence, right_data, padded_size)
        if left.size != right.size:
            raise RuntimeError("OFDM lane sizes diverged")
        return np.column_stack((left, right)).astype(np.float32, copy=False)

    def _find_start(self, samples: NDArray[np.float32]) -> int:
        search_end = min(
            samples.size,
            self.config.sample_rate * _MAX_STARTUP_SECONDS
            + self._acquisition_template.size,
        )
        search = samples[:search_end]
        if search.size < self._acquisition_template.size:
            return 0
        correlation = np.correlate(search, self._acquisition_template, mode="valid")
        return int(np.argmax(np.abs(correlation)))

    def _demodulate_blocks(
        self, blocks: NDArray[np.float32], channel: NDArray[np.complexfloating]
    ) -> NDArray[np.uint8]:
        coefficients = blocks @ np.conj(self._basis).T
        equalized = coefficients / channel
        return (
            np.rint((np.angle(equalized) % (2 * np.pi)) / self._phase_step).astype(int)
            % self._modulation_order
        ).astype(np.uint8)

    @staticmethod
    def _majority_header(headers: list[bytes]) -> bytes:
        result = bytearray(len(headers[0]))
        for index in range(len(result)):
            values = [header[index] for header in headers]
            result[index] = max(set(values), key=values.count)
        return bytes(result)

    def _decode_lane(self, samples: NDArray[np.float32], start: int) -> dict[int, bytes]:
        frames: dict[int, bytes] = {}
        position = start
        first_frame = True
        while True:
            sync_blocks = _ACQUISITION_BLOCKS if first_frame else _SYNC_BLOCKS
            sync_coefficients_expected = (
                self._acquisition_coefficients
                if first_frame
                else self._sync_coefficients
            )
            header_block_count = _HEADER_REPETITIONS * self._header_blocks
            minimum_blocks = sync_blocks + header_block_count
            if position + minimum_blocks * self._count > samples.size:
                break
            sync = samples[
                position : position + sync_blocks * self._count
            ].reshape(sync_blocks, self._count)
            sync_coefficients = sync @ np.conj(self._basis).T
            channel = np.mean(
                sync_coefficients / sync_coefficients_expected,
                axis=0,
            )
            if float(np.mean(np.abs(channel))) < 1e-4:
                break
            header_at = position + sync_blocks * self._count
            header_samples = samples[
                header_at : header_at + header_block_count * self._count
            ].reshape(_HEADER_REPETITIONS, self._header_blocks, self._count)
            headers = [
                _symbols_to_bytes(
                    self._demodulate_blocks(repetition, channel).reshape(-1),
                    _PHY_HEADER.size,
                    self.config.bits_per_symbol,
                )
                for repetition in header_samples
            ]
            header = self._majority_header(headers)
            sequence, protected_length = _PHY_HEADER.unpack(header)
            if protected_length == 0 or protected_length > 65_535:
                break
            body_length = protected_length + _PHY_CRC.size
            body_blocks = math.ceil(body_length / self._bytes_per_block)
            frame_blocks = minimum_blocks + body_blocks
            frame_end = position + frame_blocks * self._count
            if frame_end > samples.size:
                break
            body_at = header_at + header_block_count * self._count
            body_samples = samples[body_at:frame_end].reshape(body_blocks, self._count)
            body_symbols = self._demodulate_blocks(body_samples, channel).reshape(-1)
            body = _symbols_to_bytes(
                body_symbols, body_length, self.config.bits_per_symbol
            )
            recovered = self._fec.decode(body[:protected_length])
            received_crc = _PHY_CRC.unpack(body[-_PHY_CRC.size :])[0]
            if (
                recovered is not None
                and zlib.crc32(header + recovered) == received_crc
                and len(recovered) >= _LANE_LENGTH.size
            ):
                lane_length = _LANE_LENGTH.unpack_from(recovered)[0]
                lane_data = recovered[_LANE_LENGTH.size :]
                if lane_length <= len(lane_data):
                    frames.setdefault(sequence, lane_data[:lane_length])
            position = frame_end
            first_frame = False
        return frames

    def demodulate(self, samples: ArrayLike) -> bytes:
        values = np.asarray(samples, dtype=np.float32)
        if values.ndim != 2 or values.shape[1] != 2:
            raise ValueError("stereo-ofdm-psk requires PCM shaped as (frames, 2)")
        start = self._find_start(values[:, 0])
        left = self._decode_lane(values[:, 0], start)
        right = self._decode_lane(values[:, 1], start)
        output = bytearray()
        for sequence in sorted(left.keys() & right.keys()):
            lane_left = left[sequence]
            lane_right = right[sequence]
            for index in range(max(len(lane_left), len(lane_right))):
                if index < len(lane_left):
                    output.append(lane_left[index])
                if index < len(lane_right):
                    output.append(lane_right[index])
        return bytes(output)

    def new_demodulator(self) -> BufferedStereoOFDMPSKDemodulator:
        return BufferedStereoOFDMPSKDemodulator(self)


class BufferedStereoOFDMPSKDemodulator:
    def __init__(self, modem: StereoOFDMPSKModem) -> None:
        self.modem = modem
        self._chunks: list[NDArray[np.float32]] = []

    def push(self, samples: ArrayLike) -> bytes:
        values = np.asarray(samples, dtype=np.float32)
        if values.size:
            if values.ndim != 2 or values.shape[1] != 2:
                raise ValueError("stereo-ofdm-psk requires PCM shaped as (frames, 2)")
            self._chunks.append(values.copy())
        return b""

    def finish(self) -> bytes:
        if not self._chunks:
            return b""
        samples = np.concatenate(self._chunks, axis=0)
        self._chunks.clear()
        return self.modem.demodulate(samples)
