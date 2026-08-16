from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import ArrayLike, NDArray

from kotone.config import ModemConfig


class Demodulator(Protocol):
    def push(self, samples: ArrayLike) -> bytes: ...

    def finish(self) -> bytes: ...


class Modem(Protocol):
    config: ModemConfig

    def modulate(self, data: bytes) -> NDArray[np.float32]: ...

    def demodulate(self, samples: ArrayLike) -> bytes: ...

    def new_demodulator(self) -> Demodulator: ...
