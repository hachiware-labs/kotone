import pytest

from kotone import register_modem
from kotone.config import ModemConfig
from kotone.modem import create_modem


def test_custom_modem_factory_can_be_registered() -> None:
    marker = object()
    register_modem("test-marker", lambda config: marker)  # type: ignore[arg-type]
    config = ModemConfig(scheme="test-marker")
    assert create_modem(config) is marker
    with pytest.raises(ValueError, match="already registered"):
        register_modem("test-marker", lambda candidate: marker)  # type: ignore[arg-type]


def test_unknown_modem_lists_available_schemes() -> None:
    with pytest.raises(ValueError, match="stereo-ofdm-psk"):
        create_modem(ModemConfig(scheme="missing"))
