import base64
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MODELS = {"flash": "gemini-3.8-flash-tts"}

DEFAULT_VOICE = "Iapetus"
DEFAULT_MODEL = "flash"
FORMATS = ("mp3", "wav")

FLAGS = ("direction",)

VOICES = {
    "Zephyr": "Bright",
    "Puck": "Upbeat",
    "Charon": "Informative",
    "Kore": "Firm",
    "Fenrir": "Excitable",
    "Leda": "Youthful",
    "Orus": "Firm",
    "Aoede": "Breezy",
    "Callirrhoe": "Easy-going",
    "Autonoe": "Bright",
    "Enceladus": "Breathy",
    "Iapetus": "Clear",
    "Umbriel": "Easy-going",
    "Algieba": "Smooth",
    "Despina": "Smooth",
    "Erinome": "Clear",
    "Algenib": "Gravelly",
    "Rasalgethi": "Informative",
    "Laomedeia": "Upbeat",
    "Achernar": "Soft",
    "Alnilam": "Firm",
    "Schedar": "Even",
    "Gacrux": "Mature",
    "Pulcherrima": "Forward",
    "Achird": "Friendly",
    "Zubenelgenubi": "Casual",
    "Vindemiatrix": "Gentle",
    "Sadachbia": "Lively",
    "Sadaltager": "Knowledgeable",
    "Sulafat": "Warm",
}


def add_args(p):
    g = p.add_argument_group("gemini options")
    g.add_argument(
        "--direction",
        metavar="TEXT",
        help="short delivery style for the whole text, e.g. 'whispered urgently'",
    )


def list_voices():
    for name, desc in VOICES.items():
        print(f"{name}\t{desc}")


def _resolve_voice(voice):
    if voice.startswith(("voice_", "voicekey_")):
        return voice
    for name in VOICES:
        if name.lower() == voice.lower():
            return name
    print(f"error: unknown gemini voice: {voice} (see --list-voices)", file=sys.stderr)
    sys.exit(1)


def _format(args):
    fmt = args.format
    if not fmt and args.output:
        fmt = Path(args.output).suffix.lstrip(".").lower()
    fmt = fmt or "mp3"
    if fmt not in FORMATS:
        print(f"error: gemini --format must be one of: {', '.join(FORMATS)}", file=sys.stderr)
        sys.exit(1)
    return fmt


def _to_mp3(wav):
    if not shutil.which("ffmpeg"):
        print("error: ffmpeg required for mp3 output (use --format wav)", file=sys.stderr)
        sys.exit(1)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / "out.mp3"
        src.write_bytes(wav)
        proc = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-codec:a", "libmp3lame", "-q:a", "2", str(dst)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"error: ffmpeg failed: {proc.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        return dst.read_bytes()


def synthesize(args):
    if not os.environ.get("GEMINI_API_KEY"):
        print("error: GEMINI_API_KEY env var required", file=sys.stderr)
        sys.exit(1)
    model = args.model or DEFAULT_MODEL
    if model not in MODELS:
        print(f"error: gemini --model must be one of: {', '.join(MODELS)}", file=sys.stderr)
        sys.exit(1)
    voice = _resolve_voice(args.voice or DEFAULT_VOICE)
    fmt = _format(args)

    from google import genai

    item = {"type": "text", "text": args.text}
    if args.direction:
        item["annotations"] = [{"type": "speech_metadata", "style": args.direction}]

    client = genai.Client()
    interaction = client.interactions.create(
        model=MODELS[model],
        input=[{"type": "user_input", "content": [item]}],
        response_format={"type": "audio"},
        generation_config={"speech_config": [{"voice": voice}]},
    )
    audio = interaction.output_audio
    if audio is None:
        print("error: no audio in response", file=sys.stderr)
        sys.exit(1)

    wav = base64.b64decode(audio.data)
    return (_to_mp3(wav) if fmt == "mp3" else wav), fmt
