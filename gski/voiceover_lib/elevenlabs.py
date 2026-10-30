import json
import os
import re
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.elevenlabs.io/v1"

MODELS = {
    "v4": "eleven_v4",
    "multilingual": "eleven_multilingual_v2",
    "flash": "eleven_flash_v2_5",
}

# Blain - Conversational Ad Voice
DEFAULT_VOICE = "jHprmvvyQreWpRuutdmV"
DEFAULT_MODEL = "v4"
DEFAULT_FORMAT = "mp3_44100_128"

VOICE_ID_RE = re.compile(r"^[A-Za-z0-9]{20}$")

FLAGS = ("stability", "style", "similarity", "speed", "speaker_boost")


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


def _voices(key):
    with _request(f"{API_BASE}/voices", key) as resp:
        return json.load(resp).get("voices", [])


def add_args(p):
    g = p.add_argument_group("elevenlabs options")
    g.add_argument("--stability", type=float, help="0-1, lower = more expressive (default: 0.1)")
    g.add_argument("--style", type=float, help="0-1, style exaggeration (default: 1.0)")
    g.add_argument("--similarity", type=float, help="0-1, adherence to voice (default: 1.0)")
    g.add_argument("--speed", type=float, help="0.7-1.2, native speech speed (default: 1.2)")
    g.add_argument(
        "--no-speaker-boost",
        action="store_const",
        const=False,
        default=None,
        dest="speaker_boost",
        help="disable speaker similarity boost",
    )


def list_voices():
    for v in _voices(_api_key()):
        print(f"{v['voice_id']}\t{v['name']}\t{v.get('category', '')}")


def _resolve_voice(voice, key):
    if VOICE_ID_RE.match(voice):
        return voice
    voices = _voices(key)
    for v in voices:
        if v["name"].lower() == voice.lower():
            return v["voice_id"]
    for v in voices:
        if voice.lower() in v["name"].lower():
            return v["voice_id"]
    print(f"error: voice not found in library: {voice}", file=sys.stderr)
    sys.exit(1)


def _opt(value, default):
    return default if value is None else value


def synthesize(args):
    key = _api_key()
    model = args.model or DEFAULT_MODEL
    if model not in MODELS:
        print(f"error: elevenlabs --model must be one of: {', '.join(MODELS)}", file=sys.stderr)
        sys.exit(1)
    fmt = args.format or DEFAULT_FORMAT
    voice_id = _resolve_voice(args.voice or DEFAULT_VOICE, key)

    payload = {
        "text": args.text,
        "model_id": MODELS[model],
        "voice_settings": {
            "stability": _opt(args.stability, 0.1),
            "similarity_boost": _opt(args.similarity, 1.0),
            "style": _opt(args.style, 1.0),
            "use_speaker_boost": _opt(args.speaker_boost, True),
            "speed": _opt(args.speed, 1.2),
        },
    }

    url = f"{API_BASE}/text-to-speech/{voice_id}?output_format={fmt}"
    try:
        with _request(url, key, method="POST", payload=payload) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as e:
        print(f"error: HTTP {e.code}: {e.read().decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)

    return audio, fmt.split("_")[0]
