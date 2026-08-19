from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

from kotone.benchmark import benchmark
from kotone.channel.noise import add_noise_wav
from kotone.channel.sbc import sbc_round_trip
from kotone.channel.wav import decode_wav, encode_wav
from kotone.codec import DecodeError
from kotone.config import codec_config_for_profile
from kotone.file_payload import pack_file_payload, try_unpack_file_payload
from kotone.resume import ResumeToken, validate_resume_data

DEMO_PROFILES = (
    "reliable",
    "fast",
    "a2dp",
    "a2dp-stereo",
    "a2dp-stereo-fec",
    "a2dp-ofdm-441",
    "a2dp-ofdm-328",
    "a2dp-ofdm-328-robust",
    "a2dp-ofdm",
)


def _add_modem_options(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--packet-size",
        type=int,
        default=None,
        help=(
            "payload bytes per packet (default: 512; "
            "a2dp-ofdm-441/328 profiles: 4096; a2dp-ofdm: 1024)"
        ),
    )
    command.add_argument(
        "--profile",
        choices=(
            "reliable",
            "fast",
            "a2dp",
            "a2dp-stereo",
            "a2dp-stereo-fec",
            "a2dp-ofdm-441",
            "a2dp-ofdm-328",
            "a2dp-ofdm-328-robust",
            "a2dp-ofdm",
        ),
        default="reliable",
        help=(
            "modem profile: reliable=2.4, fast=9.6, a2dp=12, "
            "a2dp-stereo=19.2, a2dp-stereo-fec=24, "
            "a2dp-ofdm-441=67.2, a2dp-ofdm-328=64, "
            "a2dp-ofdm-328-robust=64, "
            "a2dp-ofdm=96 kbit/s"
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kotone", description="Binary data over PCM audio")
    parser.add_argument("--version", action="version", version="kotone 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)

    encode_command = commands.add_parser("encode", help="encode a binary file as WAV")
    encode_command.add_argument("input", type=Path)
    encode_command.add_argument("output", type=Path)
    encode_command.add_argument(
        "--startup-silence-ms",
        type=float,
        default=None,
        help=(
            "silence before the signal; default: 500 for a2dp-ofdm-441, "
            "0 for other profiles"
        ),
    )
    encode_command.add_argument(
        "--resume-token",
        help=(
            "resume token shown by the receiving PC; validates the original "
            "file and emits only the still-needed packets"
        ),
    )
    _add_modem_options(encode_command)

    decode_command = commands.add_parser("decode", help="decode a Kotone WAV file")
    decode_command.add_argument("input", type=Path)
    decode_command.add_argument(
        "output",
        type=Path,
        nargs="?",
        help=(
            "output file; omit it to restore the embedded UTF-8 filename "
            "from a KTF1 file payload"
        ),
    )
    _add_modem_options(decode_command)

    noise_command = commands.add_parser(
        "noise", help="add white Gaussian noise to a PCM WAV"
    )
    noise_command.add_argument("input", type=Path)
    noise_command.add_argument("output", type=Path)
    noise_command.add_argument(
        "--snr-db",
        type=float,
        default=20.0,
        help="RMS signal-to-noise ratio in dB (default: 20)",
    )
    noise_command.add_argument(
        "--seed", type=int, default=None, help="reproducible random seed"
    )

    bench_command = commands.add_parser("bench", help="run an in-memory digital loopback")
    bench_command.add_argument("input", type=Path)
    _add_modem_options(bench_command)
    bench_command.add_argument(
        "--channel",
        choices=("digital", "sbc"),
        default="digital",
        help="loopback channel; sbc requires the optional 'sbc' dependency",
    )
    bench_command.add_argument(
        "--sbc-bitrate",
        type=int,
        default=None,
        help="SBC bit/s (profile default: 328000; a2dp-ofdm: 512000)",
    )
    bench_command.add_argument("--json", action="store_true")

    demo_command = commands.add_parser(
        "demo", help="create short listening samples for modem profiles"
    )
    demo_command.add_argument("input", type=Path)
    demo_command.add_argument("output_dir", type=Path)
    demo_command.add_argument("--duration", type=float, default=3.0)
    demo_command.add_argument(
        "--profiles",
        nargs="+",
        choices=DEMO_PROFILES,
        default=list(DEMO_PROFILES),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "demo":
            if args.duration <= 0:
                raise ValueError("duration must be positive")
            source = args.input.read_bytes() or b"\x00"
            args.output_dir.mkdir(parents=True, exist_ok=True)
            for index, profile in enumerate(args.profiles, start=1):
                config = codec_config_for_profile(profile)
                target_bytes = max(
                    1,
                    round(args.duration * config.modem.raw_bitrate / 8 * 0.75),
                )
                repeat_count = (target_bytes + len(source) - 1) // len(source)
                payload = (source * repeat_count)[:target_bytes]
                output = args.output_dir / f"{index:02d}-{profile}.wav"
                encode_wav(
                    payload,
                    output,
                    config,
                    startup_silence_seconds=(
                        0.5 if profile == "a2dp-ofdm-441" else 0.0
                    ),
                )
                with wave.open(str(output), "rb") as generated:
                    audio_seconds = generated.getnframes() / generated.getframerate()
                print(
                    f"{profile:22} {config.modem.raw_bitrate:6} bit/s  "
                    f"{audio_seconds:6.2f} s  {output}"
                )
            return 0

        if args.command == "noise":
            result = add_noise_wav(
                args.input,
                args.output,
                snr_db=args.snr_db,
                seed=args.seed,
            )
            print(f"SNR           : {result.snr_db:.2f} dB")
            print(f"Signal RMS    : {result.signal_rms:.6f}")
            print(f"Noise RMS     : {result.noise_rms:.6f}")
            print(f"Clipped       : {result.clipped_samples} samples")
            return 0

        config = codec_config_for_profile(
            args.profile, packet_payload_size=args.packet_size
        )
        if args.command == "encode":
            data = pack_file_payload(args.input.name, args.input.read_bytes())
            resume = (
                ResumeToken.parse(args.resume_token)
                if args.resume_token is not None
                else None
            )
            if resume is not None:
                validate_resume_data(
                    resume,
                    data,
                    packet_payload_size=config.packet_payload_size,
                )
                packet_count = max(
                    1,
                    (len(data) + config.packet_payload_size - 1)
                    // config.packet_payload_size,
                )
                print(
                    f"Resume stream {resume.stream_id:08X} from packet "
                    f"{resume.next_sequence}/{packet_count - 1} "
                    f"after {resume.accepted_bytes} bytes"
                )
            startup_silence_seconds = (
                args.startup_silence_ms / 1_000
                if args.startup_silence_ms is not None
                else 0.5 if args.profile == "a2dp-ofdm-441" else 0.0
            )
            encode_wav(
                data,
                args.output,
                config,
                startup_silence_seconds=startup_silence_seconds,
                stream_id=resume.stream_id if resume is not None else None,
                start_sequence=(
                    resume.next_sequence if resume is not None else 0
                ),
            )
            return 0
        if args.command == "decode":
            data = decode_wav(args.input, config)
            file_payload = try_unpack_file_payload(data)
            if file_payload is None:
                if args.output is None:
                    raise ValueError(
                        "legacy payload has no embedded filename; specify output"
                    )
                output = args.output
            else:
                output = args.output or Path(file_payload.filename)
                data = file_payload.data
            output.write_bytes(data)
            return 0
        if args.command == "bench":
            channel = None
            if args.channel == "sbc":
                sbc_bitrate = args.sbc_bitrate or (
                    512_000 if args.profile == "a2dp-ofdm" else 328_000
                )
                channel = lambda samples: sbc_round_trip(
                    samples,
                    sample_rate=config.modem.sample_rate,
                    bitrate=sbc_bitrate,
                )
            result = benchmark(
                args.input.read_bytes(),
                config,
                channel=channel,
                channel_name=args.channel,
            )
            if args.json:
                print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            else:
                print(f"Channel       : {result.channel}")
                print(f"Decode        : {'SUCCESS' if result.success else 'FAILURE'}")
                print(f"Payload       : {result.payload_bytes} bytes")
                print(f"Audio         : {result.audio_seconds:.3f} s")
                print(f"Goodput       : {result.payload_goodput_bps:.2f} B/s")
                print(f"Raw bitrate   : {result.raw_bitrate_bps} bit/s")
                print(f"BER           : {result.bit_error_rate:.6g}")
                print(f"Packet Error  : {result.packet_error_rate:.6g}")
                print(f"CRC errors    : {result.crc_errors}")
                print(f"Lost packets  : {result.lost_packets}")
                print(f"FEC corrected : {result.fec_corrections}")
            return 0 if result.success else 1
    except (OSError, RuntimeError, ValueError, DecodeError) as error:
        print(f"kotone: {error}", file=sys.stderr)
        return 2
    return 2
