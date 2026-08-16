from kotone import codec_config_for_profile
from kotone.benchmark import benchmark


def test_benchmark_reports_success() -> None:
    result = benchmark(bytes(range(256)))
    assert result.success
    assert result.bit_error_rate == 0
    assert result.packet_error_rate == 0
    assert result.payload_goodput_bps > 0
    assert result.raw_bitrate_bps == 2_400


def test_fast_profile_benchmark_exceeds_one_kilobyte_per_second() -> None:
    result = benchmark(bytes(range(256)) * 4, codec_config_for_profile("fast"))
    assert result.success
    assert result.raw_bitrate_bps == 9_600
    assert result.payload_goodput_bps > 1_000


def test_a2dp_profile_benchmark_exceeds_1_3_kilobytes_per_second() -> None:
    result = benchmark(bytes(range(256)) * 4, codec_config_for_profile("a2dp"))
    assert result.success
    assert result.channel == "digital"
    assert result.raw_bitrate_bps == 12_000
    assert result.payload_goodput_bps > 1_300


def test_stereo_a2dp_benchmark_exceeds_two_kilobytes_per_second() -> None:
    result = benchmark(
        bytes(range(256)) * 4, codec_config_for_profile("a2dp-stereo")
    )
    assert result.success
    assert result.raw_bitrate_bps == 19_200
    assert result.payload_goodput_bps > 2_000


def test_stereo_fec_benchmark_reaches_2_4_kilobytes_per_second() -> None:
    result = benchmark(
        bytes(range(256)) * 16,
        codec_config_for_profile("a2dp-stereo-fec"),
    )
    assert result.success
    assert result.raw_bitrate_bps == 24_000
    assert result.payload_goodput_bps > 2_400
    assert result.fec_corrections == 0


def test_stereo_ofdm_benchmark_exceeds_ten_kilobytes_per_second() -> None:
    result = benchmark(
        bytes(range(256)) * 16,
        codec_config_for_profile("a2dp-ofdm"),
    )
    assert result.success
    assert result.raw_bitrate_bps == 96_000
    assert result.payload_goodput_bps > 10_000


def test_stereo_qpsk_ofdm_328_exceeds_seven_kilobytes_per_second() -> None:
    result = benchmark(
        bytes(range(256)) * 32,
        codec_config_for_profile("a2dp-ofdm-328"),
    )
    assert result.success
    assert result.raw_bitrate_bps == 64_000
    assert result.payload_goodput_bps > 7_000


def test_stereo_qpsk_ofdm_328_robust_exceeds_6_7_kilobytes_per_second() -> None:
    result = benchmark(
        bytes(range(256)) * 128,
        codec_config_for_profile("a2dp-ofdm-328-robust"),
    )
    assert result.success
    assert result.raw_bitrate_bps == 64_000
    assert result.payload_goodput_bps > 6_700
