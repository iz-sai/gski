import sys
from datetime import datetime
from pathlib import Path

from gski.voiceover_lib import elevenlabs, gemini

PROVIDERS = {"elevenlabs": elevenlabs, "gemini": gemini}


def register(subparsers):
    p = subparsers.add_parser(
        "voiceover",
        aliases=["tts"],
        help="text-to-speech voiceover (ElevenLabs, Gemini)",
    )
    p.add_argument("text", nargs="?", help="text to synthesize (tag syntax depends on provider)")
    p.add_argument(
        "--provider",
        choices=list(PROVIDERS),
        default="elevenlabs",
        help="TTS backend (default: elevenlabs)",
    )
    p.add_argument(
        "--voice",
        help="elevenlabs: library name or voice_id (default: Blain); gemini: prebuilt name or voice_... id (default: Iapetus)",
    )
    p.add_argument(
        "--model",
        help="elevenlabs: v4|multilingual|flash (default: v4); gemini: flash (default)",
    )
    p.add_argument(
        "--format",
        help="elevenlabs: codec_rate_bitrate (default: mp3_44100_128); gemini: mp3|wav (default: mp3)",
    )
    p.add_argument("--output-dir", default="./output", help="output directory (default: ./output)")
    p.add_argument("-o", "--output", metavar="FILE", help="output file path (overrides --output-dir and auto-naming)")
    p.add_argument("--list-voices", action="store_true", help="list voices of the provider and exit")
    for mod in PROVIDERS.values():
        mod.add_args(p)
    p.set_defaults(func=run)


def _reject_foreign_flags(args):
    flags = {"--" + d.replace("_", "-"): d for name, mod in PROVIDERS.items() if name != args.provider for d in mod.FLAGS}
    for flag, dest in flags.items():
        if getattr(args, dest) is not None:
            print(f"error: {flag} is not supported by provider {args.provider}", file=sys.stderr)
            sys.exit(1)


def run(args):
    provider = PROVIDERS[args.provider]
    _reject_foreign_flags(args)

    if args.list_voices:
        provider.list_voices()
        return

    if not args.text:
        print("error: text is required", file=sys.stderr)
        sys.exit(1)

    audio, ext = provider.synthesize(args)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"voiceover_{ts}.{ext}"

    out_path.write_bytes(audio)
    print(out_path)
