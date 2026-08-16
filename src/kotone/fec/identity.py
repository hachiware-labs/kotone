class IdentityFEC:
    """No-op FEC implementation used by v0.1's replaceable FEC boundary."""

    def encode(self, data: bytes) -> bytes:
        return bytes(data)

    def decode(self, data: bytes) -> bytes:
        return bytes(data)
