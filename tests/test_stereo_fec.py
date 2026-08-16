from kotone import codec_config_for_profile
from kotone.fec import ReedSolomonFEC
from kotone.modem import create_modem
from kotone.modem.stereo_fsk import StereoFourFSKModem


def test_lane_fec_corrects_interleaved_byte_errors() -> None:
    config = codec_config_for_profile("a2dp-stereo-fec")
    modem = create_modem(config.modem)
    assert isinstance(modem, StereoFourFSKModem)
    original = bytes(index % 251 for index in range(500))
    protected = bytearray(modem._protect(original))
    for index in range(4):
        protected[index] ^= 0x55
    assert modem._recover(bytes(protected)) == original
    assert modem.corrected_symbols == 4


def test_robust_fec_corrects_sixteen_interleaved_symbol_errors() -> None:
    fec = ReedSolomonFEC(32, interleave=True)
    original = bytes(index % 251 for index in range(1_000))
    protected = bytearray(fec.encode(original))
    for index in range(16):
        protected[index] ^= 0xA5
    assert fec.decode(bytes(protected)) == original
    assert fec.corrected_symbols == 16
