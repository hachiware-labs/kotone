from __future__ import annotations

import struct
import zlib
from dataclasses import replace

import numpy as np
from numpy.typing import ArrayLike, NDArray

from kotone.config import ModemConfig
from kotone.fec import ReedSolomonFEC
from kotone.framing.packet import PREAMBLE, SYNC_WORD
from kotone.modem.fsk import FourFSKModem

_PHY_HEADER = struct.Struct(">IH")
_PHY_CRC = struct.Struct(">I")
_PHY_PREFIX = PREAMBLE + SYNC_WORD


class StereoFourFSKModem:
    """Two independent 4-FSK byte lanes carried by stereo PCM."""

    def __init__(self, config: ModemConfig) -> None:
        if config.channel_count != 2:
            raise ValueError("stereo-4fsk requires channel_count=2")
        self.config = config
        mono_config = replace(config, scheme="4fsk", channel_count=1)
        self._lane_modem = FourFSKModem(mono_config)
        self._fec = (
            ReedSolomonFEC(config.fec_symbols, interleave=config.interleave)
            if config.fec_symbols
            else None
        )
        self._tx_sequence = 0

    def _protect(self, data: bytes) -> bytes:
        return self._fec.encode(data) if self._fec is not None else data

    def _recover(self, data: bytes) -> bytes | None:
        return self._fec.decode(data) if self._fec is not None else data

    @property
    def corrected_symbols(self) -> int:
        return self._fec.corrected_symbols if self._fec is not None else 0

    def _lane_frame(self, sequence: int, data: bytes) -> bytes:
        protected = self._protect(data)
        header = _PHY_HEADER.pack(sequence, len(protected))
        checksum_body = header + data
        return _PHY_PREFIX + header + protected + _PHY_CRC.pack(
            zlib.crc32(checksum_body)
        )

    def modulate(self, data: bytes) -> NDArray[np.float32]:
        raw = bytes(data)
        sequence = self._tx_sequence
        self._tx_sequence += 1
        left = self._lane_modem.modulate(self._lane_frame(sequence, raw[::2]))
        right = self._lane_modem.modulate(self._lane_frame(sequence, raw[1::2]))
        frame_count = max(left.size, right.size)
        result = np.zeros((frame_count, 2), dtype=np.float32)
        result[: left.size, 0] = left
        result[: right.size, 1] = right
        return result

    def _parse_lane(self, data: bytes) -> dict[int, bytes]:
        frames: dict[int, bytes] = {}
        position = 0
        minimum = len(_PHY_PREFIX) + _PHY_HEADER.size + _PHY_CRC.size
        while position + minimum <= len(data):
            prefix_at = data.find(_PHY_PREFIX, position)
            if prefix_at < 0 or prefix_at + minimum > len(data):
                break
            header_at = prefix_at + len(_PHY_PREFIX)
            sequence, length = _PHY_HEADER.unpack_from(data, header_at)
            payload_at = header_at + _PHY_HEADER.size
            end = payload_at + length + _PHY_CRC.size
            if end > len(data):
                position = prefix_at + 1
                continue
            expected_crc = _PHY_CRC.unpack_from(data, end - _PHY_CRC.size)[0]
            protected = data[payload_at : end - _PHY_CRC.size]
            recovered = self._recover(protected)
            checksum_body = data[header_at:payload_at] + (recovered or b"")
            if recovered is not None and zlib.crc32(checksum_body) == expected_crc:
                frames.setdefault(sequence, recovered)
                position = end
            else:
                position = prefix_at + 1
        return frames

    def demodulate(self, samples: ArrayLike) -> bytes:
        values = np.asarray(samples, dtype=np.float32)
        if values.ndim != 2 or values.shape[1] != 2:
            raise ValueError("stereo-4fsk requires PCM shaped as (frames, 2)")
        left = self._parse_lane(self._lane_modem.demodulate(values[:, 0]))
        right = self._parse_lane(self._lane_modem.demodulate(values[:, 1]))
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

    def new_demodulator(self) -> BufferedStereoFourFSKDemodulator:
        return BufferedStereoFourFSKDemodulator(self)


class BufferedStereoFourFSKDemodulator:
    """Initial streaming boundary; acquisition is finalized at end-of-stream."""

    def __init__(self, modem: StereoFourFSKModem) -> None:
        self.modem = modem
        self._chunks: list[NDArray[np.float32]] = []

    def push(self, samples: ArrayLike) -> bytes:
        values = np.asarray(samples, dtype=np.float32)
        if values.size:
            if values.ndim != 2 or values.shape[1] != 2:
                raise ValueError("stereo-4fsk requires PCM shaped as (frames, 2)")
            self._chunks.append(values.copy())
        return b""

    def finish(self) -> bytes:
        if not self._chunks:
            return b""
        samples = np.concatenate(self._chunks, axis=0)
        self._chunks.clear()
        return self.modem.demodulate(samples)
