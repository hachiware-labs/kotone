from __future__ import annotations

from reedsolo import ReedSolomonError, RSCodec


class ReedSolomonFEC:
    """Chunked GF(2^8) Reed-Solomon codec with optional block interleave."""

    def __init__(self, parity_symbols: int = 8, *, interleave: bool = True) -> None:
        if not 1 <= parity_symbols < 255:
            raise ValueError("parity_symbols must be in [1, 254]")
        self.parity_symbols = parity_symbols
        self.interleave = interleave
        self.corrected_symbols = 0
        self._codec = RSCodec(parity_symbols)

    def _interleave(self, data: bytes) -> bytes:
        if not self.interleave or len(data) <= 255:
            return data
        chunks = [data[offset : offset + 255] for offset in range(0, len(data), 255)]
        return bytes(
            chunk[column]
            for column in range(max(map(len, chunks)))
            for chunk in chunks
            if column < len(chunk)
        )

    def _deinterleave(self, data: bytes) -> bytes:
        if not self.interleave or len(data) <= 255:
            return data
        lengths = [255] * (len(data) // 255)
        remainder = len(data) % 255
        if remainder:
            lengths.append(remainder)
        chunks = [bytearray(length) for length in lengths]
        position = 0
        for column in range(max(lengths)):
            for chunk in chunks:
                if column < len(chunk):
                    chunk[column] = data[position]
                    position += 1
        return b"".join(chunks)

    def encode(self, data: bytes) -> bytes:
        return self._interleave(bytes(self._codec.encode(data)))

    def decode(self, data: bytes) -> bytes | None:
        try:
            decoded, _, errata = self._codec.decode(self._deinterleave(data))
        except ReedSolomonError:
            return None
        self.corrected_symbols += len(errata)
        return bytes(decoded)
