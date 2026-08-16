from collections.abc import Callable

from kotone.config import ModemConfig
from kotone.modem.base import Modem
from kotone.modem.fsk import FourFSKDemodulator, FourFSKModem
from kotone.modem.ofdm import StereoOFDMPSKModem
from kotone.modem.stereo_fsk import StereoFourFSKModem

ModemFactory = Callable[[ModemConfig], Modem]
_MODEM_FACTORIES: dict[str, ModemFactory] = {
    "4fsk": FourFSKModem,
    "stereo-4fsk": StereoFourFSKModem,
    "stereo-ofdm-psk": StereoOFDMPSKModem,
}


def register_modem(name: str, factory: ModemFactory, *, replace: bool = False) -> None:
    if not name:
        raise ValueError("modem name must not be empty")
    if name in _MODEM_FACTORIES and not replace:
        raise ValueError(f"modem is already registered: {name}")
    _MODEM_FACTORIES[name] = factory


def create_modem(config: ModemConfig) -> Modem:
    try:
        factory = _MODEM_FACTORIES[config.scheme]
    except KeyError as error:
        available = ", ".join(sorted(_MODEM_FACTORIES))
        raise ValueError(
            f"unknown modem scheme: {config.scheme}; available: {available}"
        ) from error
    return factory(config)


def available_modems() -> tuple[str, ...]:
    return tuple(sorted(_MODEM_FACTORIES))


__all__ = [
    "FourFSKDemodulator",
    "FourFSKModem",
    "StereoFourFSKModem",
    "StereoOFDMPSKModem",
    "available_modems",
    "create_modem",
    "register_modem",
]
