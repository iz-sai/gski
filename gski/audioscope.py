import json
import os
import sys
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types


MODELS = {
    "flash": "gemini-3-flash-preview",
    "pro": "gemini-3-pro-preview",
}

PROMPT_TRANSCRIBE = "Generate a transcript of the speech."

PROMPT_TRANSCRIBE_TS = (
    "Generate a transcript of the speech. "
    "Provide accurate timestamps for each segment in MM:SS format."
)

PROMPT_DIARIZE = (
    "Generate a transcript of the speech with speaker diarization. "
    "Identify and label each speaker (Speaker 1, Speaker 2, etc). "
    "Group consecutive speech by the same speaker into segments."
)

PROMPT_DIARIZE_TS = (
    "Generate a transcript of the speech with speaker diarization. "
    "Identify and label each speaker (Speaker 1, Speaker 2, etc). "
    "Group consecutive speech by the same speaker into segments. "
    "Provide accurate timestamps for each segment in MM:SS format."
)

DIARIZE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "summary": types.Schema(
            type=types.Type.STRING,
            description="A concise summary of the audio content.",
        ),
        "segments": types.Schema(
            type=types.Type.ARRAY,
            description="List of transcribed segments.",
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "speaker": types.Schema(type=types.Type.STRING),
                    "timestamp": types.Schema(type=types.Type.STRING),
                    "content": types.Schema(type=types.Type.STRING),
                },
                required=["speaker", "content"],
            ),
        ),
    },
    required=["summary", "segments"],
)

DIARIZE_TS_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "summary": types.Schema(
            type=types.Type.STRING,
            description="A concise summary of the audio content.",
        ),
        "segments": types.Schema(
            type=types.Type.ARRAY,
            description="List of transcribed segments with timestamps.",
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "speaker": types.Schema(type=types.Type.STRING),
                    "timestamp": types.Schema(type=types.Type.STRING),
                    "content": types.Schema(type=types.Type.STRING),
                },
                required=["speaker", "timestamp", "content"],
            ),
        ),
    },
    required=["summary", "segments"],
)


def default_prompt(args):
    if args.diarize and args.timestamps:
        return PROMPT_DIARIZE_TS
    if args.diarize:
        return PROMPT_DIARIZE
    if args.timestamps:
        return PROMPT_TRANSCRIBE_TS
    return PROMPT_TRANSCRIBE


def build_config(args):
    if not args.diarize:
        return None
    schema = DIARIZE_TS_SCHEMA if args.timestamps else DIARIZE_SCHEMA
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
    )


def build_contents(prompt, audio_paths, youtube_urls):
    contents = []

    for p in audio_paths:
        with open(p, "rb") as f:
            data = f.read()
        mime = _mime_type(p)
        contents.append(types.Part.from_bytes(data=data, mime_type=mime))

    for url in youtube_urls:
        contents.append(types.Part(file_data=types.FileData(file_uri=url)))

    contents.append(prompt)
    return contents


def build_contents_uploaded(prompt, uploaded_files, youtube_urls):
    contents = []

    for f in uploaded_files:
        contents.append(f)

    for url in youtube_urls:
        contents.append(types.Part(file_data=types.FileData(file_uri=url)))

    contents.append(prompt)
    return contents


def _mime_type(path):
    ext = Path(path).suffix.lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mp3",
        ".aiff": "audio/aiff",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }.get(ext, "audio/mpeg")


def _file_size(paths):
    return sum(os.path.getsize(p) for p in paths)


def format_diarize(data):
    lines = []
    if data.get("summary"):
        lines.append(f"Summary: {data['summary']}")
        lines.append("")
    for seg in data.get("segments", []):
        speaker = seg.get("speaker", "Unknown")
        ts = seg.get("timestamp", "")
        prefix = f"[{ts}] {speaker}" if ts else speaker
        lines.append(f"{prefix}: {seg['content']}")
    return "\n".join(lines)


def register(subparsers):
    p = subparsers.add_parser(
        "audioscope", help="transcribe and diarize audio via Gemini"
    )
    p.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="custom prompt (default: auto-selected based on flags)",
    )
    p.add_argument(
        "--audio",
        action="append",
        default=[],
        metavar="FILE",
        help="input audio file (repeatable)",
    )
    p.add_argument(
        "--youtube",
        action="append",
        default=[],
        metavar="URL",
        help="YouTube URL (repeatable)",
    )
    p.add_argument(
        "--model",
        choices=list(MODELS.keys()),
        default="flash",
        help="model to use (default: flash)",
    )
    p.add_argument(
        "--diarize",
        action="store_true",
        help="speaker diarization mode (structured JSON)",
    )
    p.add_argument(
        "--timestamps",
        action="store_true",
        help="include MM:SS timestamps in output",
    )
    p.add_argument(
        "--output-dir",
        default="./output",
        help="output directory for saving results (default: ./output)",
    )
    p.set_defaults(func=run)


UPLOAD_THRESHOLD = 15 * 1024 * 1024  # 15 MB — leave room for prompt overhead


def run(args):
    if not args.audio and not args.youtube:
        print("error: at least one --audio or --youtube required", file=sys.stderr)
        sys.exit(1)

    for p in args.audio:
        if not os.path.isfile(p):
            print(f"error: audio file not found: {p}", file=sys.stderr)
            sys.exit(1)

    if not os.environ.get("GEMINI_API_KEY"):
        print("error: GEMINI_API_KEY env var required", file=sys.stderr)
        sys.exit(1)

    prompt = args.prompt or default_prompt(args)
    client = genai.Client()
    model = MODELS[args.model]
    config = build_config(args)

    if args.audio and _file_size(args.audio) > UPLOAD_THRESHOLD:
        uploaded = []
        for p in args.audio:
            print(f"uploading {p}...", file=sys.stderr)
            uploaded.append(client.files.upload(file=p))
        contents = build_contents_uploaded(prompt, uploaded, args.youtube)
    else:
        contents = build_contents(prompt, args.audio, args.youtube)

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.diarize:
        raw_path = output_dir / f"audioscope_{ts}.raw.txt"
        raw_path.write_text(response.text or "")
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"error: failed to parse JSON response: {e}", file=sys.stderr)
            print(f"raw response saved: {raw_path}", file=sys.stderr)
            print(f"response length: {len(response.text or '')} chars", file=sys.stderr)
            sys.exit(2)
        json_path = output_dir / f"audioscope_{ts}.json"
        json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(format_diarize(data))
        print(f"\nsaved: {json_path}", file=sys.stderr)
    else:
        txt_path = output_dir / f"audioscope_{ts}.txt"
        txt_path.write_text(response.text)
        print(response.text)
        print(f"\nsaved: {txt_path}", file=sys.stderr)
