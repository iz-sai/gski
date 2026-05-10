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
    if isinstance(data, dict) and data.get("summary"):
        lines.append(f"Summary: {data['summary']}")
        lines.append("")
    segments = data if isinstance(data, list) else data.get("segments", [])
    for seg in segments:
        speaker = seg.get("s") or seg.get("speaker") or "Unknown"
        ts = seg.get("t") or seg.get("timestamp") or ""
        text = seg.get("x") or seg.get("content") or ""
        if speaker == "__system__":
            prefix = f"[{ts}] [SYSTEM]" if ts else "[SYSTEM]"
        else:
            prefix = f"[{ts}] {speaker}" if ts else speaker
        lines.append(f"{prefix}: {text}")
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
    p.add_argument(
        "--chunk-len-sec",
        type=int,
        default=900,
        help="chunk length in seconds for long audio (default: 900 = 15 min)",
    )
    p.add_argument(
        "--overlap-sec",
        type=int,
        default=30,
        help="overlap between chunks in seconds (default: 30)",
    )
    p.add_argument(
        "--no-chunking",
        action="store_true",
        help="force single-shot even on long audio (debug)",
    )
    p.add_argument(
        "--salvage",
        action="store_true",
        help="enable salvage pass for failed chunks (pro fallback + sub-chunking)",
    )
    p.add_argument(
        "--salvage-model",
        default="pro",
        choices=list(MODELS),
        help="model for salvage pro-fallback (default: pro)",
    )
    p.add_argument(
        "--salvage-subchunk-sec",
        type=int,
        default=180,
        help="sub-chunk length in seconds for salvage (default: 180)",
    )
    p.add_argument(
        "--salvage-max-depth",
        type=int,
        default=2,
        help="salvage ladder depth: 1=pro only, 2=+flash subchunk, 3=+pro subchunk (default: 2)",
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

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Long-audio chunked path: diarize + single local audio file + not disabled.
    if (
        args.diarize
        and len(args.audio) == 1
        and not args.youtube
        and not args.no_chunking
    ):
        from gski.audioscope_utils import probe_duration
        from gski.audioscope_pipeline import transcribe_long
        import tempfile

        try:
            duration = probe_duration(args.audio[0])
        except (RuntimeError, FileNotFoundError) as e:
            print(f"warning: could not probe duration ({e}); using single-shot path", file=sys.stderr)
            duration = 0.0

        threshold = args.chunk_len_sec + args.overlap_sec + 60
        if duration > threshold:
            print(
                f"long audio detected ({duration:.0f}s > {threshold}s threshold), chunking...",
                file=sys.stderr,
            )
            with tempfile.TemporaryDirectory(prefix="audioscope_chunks_") as tmp_dir:
                result = transcribe_long(
                    client,
                    audio_path=args.audio[0],
                    model=model,
                    diarize=args.diarize,
                    timestamps=args.timestamps,
                    chunk_len_sec=args.chunk_len_sec,
                    overlap_sec=args.overlap_sec,
                    tmp_dir=tmp_dir,
                    output_dir=output_dir,
                    salvage=args.salvage,
                    salvage_model=MODELS[args.salvage_model],
                    salvage_subchunk_sec=args.salvage_subchunk_sec,
                    salvage_max_depth=args.salvage_max_depth,
                )
            print(format_diarize(result["segments"]))
            for w in result["warnings"]:
                print(f"warning: {w}", file=sys.stderr)
            # Write top-level legacy-shape JSON alongside the debug run dir, so
            # downstream consumers (meet-transcribe, vm-transcribe) that
            # glob output_dir/*.json keep working.
            from gski.audioscope_pipeline import flat_segments_to_legacy_dict
            run_dir_path = Path(result["run_dir"])
            legacy_json_path = output_dir / f"{run_dir_path.name}.json"
            legacy = flat_segments_to_legacy_dict(result["segments"])
            legacy_json_path.write_text(
                json.dumps(legacy, indent=2, ensure_ascii=False)
            )
            print(f"\nsaved: {legacy_json_path}", file=sys.stderr)
            print(f"debug artifacts: {run_dir_path}", file=sys.stderr)
            return

    # Short-audio / non-diarize path: single-shot with hardened config for diarize.
    if args.diarize:
        from gski.audioscope_gemini import build_diarize_config
        config = build_diarize_config(timestamps=args.timestamps)
    else:
        config = None

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
