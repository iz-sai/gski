import mimetypes
import os
import sys
from pathlib import Path

from google import genai
from google.genai import types


MODELS = {
    "flash": "gemini-3.5-flash",
    "pro": "gemini-3.1-pro-preview",
}

BINARY_MIMES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
    "video/mp4",
    "video/webm",
}


def guess_mime(path):
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "text/plain"


def load_file_part(path):
    p = Path(path)
    if not p.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    mime = guess_mime(p)
    if mime in BINARY_MIMES:
        return types.Part.from_bytes(data=p.read_bytes(), mime_type=mime)

    try:
        text = p.read_text()
    except UnicodeDecodeError:
        return types.Part.from_bytes(data=p.read_bytes(), mime_type=mime)

    return f"--- {p.name} ---\n{text}"


def build_contents(prompt, file_paths, stdin_data):
    parts = []

    for fp in file_paths:
        parts.append(load_file_part(fp))

    if stdin_data:
        parts.append(f"--- stdin ---\n{stdin_data}")

    parts.append(prompt)
    return parts


def build_config(args):
    kwargs = {}

    if args.system:
        kwargs["system_instruction"] = args.system

    if args.json:
        kwargs["response_mime_type"] = "application/json"

    if args.no_think:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

    if not kwargs:
        return None
    return types.GenerateContentConfig(**kwargs)


def register(subparsers):
    p = subparsers.add_parser("llm-process", help="process files and text with Gemini")
    p.add_argument("prompt", help="prompt / query to send to the model")
    p.add_argument(
        "--file",
        "-f",
        action="append",
        default=[],
        dest="files",
        help="input file(s) to process (repeatable)",
    )
    p.add_argument(
        "--model",
        "-m",
        choices=list(MODELS.keys()),
        default="flash",
        help="model to use (default: flash)",
    )
    p.add_argument(
        "--system",
        "-s",
        help="system instruction for the model",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="request JSON output",
    )
    p.add_argument(
        "--no-think",
        action="store_true",
        help="disable thinking / reasoning",
    )
    p.set_defaults(func=run)


def run(args):
    if not os.environ.get("GEMINI_API_KEY"):
        print("error: GEMINI_API_KEY env var required", file=sys.stderr)
        sys.exit(1)

    stdin_data = None
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read()

    if not args.files and not stdin_data:
        print("error: provide --file or pipe data via stdin", file=sys.stderr)
        sys.exit(1)

    contents = build_contents(args.prompt, args.files, stdin_data)
    config = build_config(args)
    client = genai.Client()
    model = MODELS[args.model]

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    print(response.text)
