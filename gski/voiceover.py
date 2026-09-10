import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

API_BASE = "https://api.elevenlabs.io/v1"

MODELS = {
    "v3": "eleven_v3",
    "multilingual": "eleven_multilingual_v2",
    "flash": "eleven_flash_v2_5",
}

# Blain - Conversational Ad Voice
DEFAULT_VOICE = "jHprmvvyQreWpRuutdmV"

VOICE_ID_RE = re.compile(r"^[A-Za-z0-9]{20}$")


def _api_key():
    key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_LABS_API_KEY")
    if not key:
        print("error: ELEVENLABS_API_KEY env var required", file=sys.stderr)
        sys.exit(1)
    return key


def _request(url, key, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"xi-api-key": key}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req)


def list_voices(key):
    with _request(f"{API_BASE}/voices", key) as resp:
        data = json.load(resp)
    for v in data.get("voices", []):
        print(f"{v['voice_id']}\t{v['name']}\t{v.get('category', '')}")


def resolve_voice(voice, key):
    if VOICE_ID_RE.match(voice):
        return voice
    with _request(f"{API_BASE}/voices", key) as resp:
        data = json.load(resp)
    voices = data.get("voices", [])
    for v in voices:
        if v["name"].lower() == voice.lower():
            return v["voice_id"]
    for v in voices:
        if voice.lower() in v["name"].lower():
            return v["voice_id"]
    print(f"error: voice not found in library: {voice}", file=sys.stderr)
    sys.exit(1)


def register(subparsers):
    p = subparsers.add_parser(
        "voiceover",
        aliases=["tts"],
        help="text-to-speech voiceover via ElevenLabs",
    )
    p.add_argument("text", nargs="?", help="text to synthesize (v3 audio tags allowed)")
    p.add_argument(
        "--voice",
        default=DEFAULT_VOICE,
        help="voice name (searches your library) or voice_id (default: Blain)",
    )
    p.add_argument(
        "--model",
        choices=list(MODELS.keys()),
        default="v3",
        help="model: v3 (expressive), multilingual (stable), flash (fast/cheap) (default: v3)",
    )
    p.add_argument("--stability", type=float, default=0.1, help="0-1, lower = more expressive (default: 0.1)")
    p.add_argument("--style", type=float, default=1.0, help="0-1, style exaggeration (default: 1.0)")
    p.add_argument("--similarity", type=float, default=1.0, help="0-1, adherence to voice (default: 1.0)")
    p.add_argument("--speed", type=float, default=1.2, help="0.7-1.2, native speech speed (default: 1.2)")
    p.add_argument("--no-speaker-boost", action="store_false", dest="speaker_boost", help="disable speaker similarity boost")
    p.add_argument(
        "--format",
        default="mp3_44100_128",
        help="output_format codec_rate_bitrate (default: mp3_44100_128)",
    )
    p.add_argument("--output-dir", default="./output", help="output directory (default: ./output)")
    p.add_argument("-o", "--output", metavar="FILE", help="output file path (overrides --output-dir and auto-naming)")
    p.add_argument("--list-voices", action="store_true", help="list available voices and exit")
    p.set_defaults(func=run)


def run(args):
    key = _api_key()

    if args.list_voices:
        list_voices(key)
        return

    if not args.text:
        print("error: text is required", file=sys.stderr)
        sys.exit(1)

    voice_id = resolve_voice(args.voice, key)

    payload = {
        "text": args.text,
        "model_id": MODELS[args.model],
        "voice_settings": {
            "stability": args.stability,
            "similarity_boost": args.similarity,
            "style": args.style,
            "use_speaker_boost": args.speaker_boost,
            "speed": args.speed,
        },
    }

    url = f"{API_BASE}/text-to-speech/{voice_id}?output_format={args.format}"
    try:
        with _request(url, key, method="POST", payload=payload) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as e:
        print(f"error: HTTP {e.code}: {e.read().decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)

    ext = args.format.split("_")[0]
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
