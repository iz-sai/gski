import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .models import GEMINI_IMAGE as MODELS

PROHIBITED_MODELS = {
    "flash",
    "flash2",
    "flash3",
    "pro",
    "lite",
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image",
    "gemini-3-pro-image-preview",
    "gemini-3.1-flash-lite-image",
}

ASPECT_RATIOS = [
    "1:1",
    "1:4",
    "1:8",
    "2:3",
    "3:2",
    "3:4",
    "4:1",
    "4:3",
    "4:5",
    "5:4",
    "8:1",
    "9:16",
    "16:9",
    "21:9",
]
SIZES = ["1K", "2K", "4K"]

VERTEX_CRED_PATH = Path.home() / ".config" / "gski" / "gemcred.json"
VERTEX_LOCATION = "global"
VERTEX_API_REVISION = "2026-05-20"

genai = None
types = None
Image = None


def _init_deps():
    global genai, types, Image
    if genai is None:
        from google import genai as _genai
        from google.genai import types as _types
        from PIL import Image as _Image

        genai = _genai
        types = _types
        Image = _Image


def build_config(args):
    kwargs = {
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(
            disable=True
        ),
        "thinking_config": types.ThinkingConfig(
            thinking_level="MEDIUM" if args.thinking else "MINIMAL"
        ),
    }

    image_config_kwargs = {}
    if args.aspect_ratio:
        image_config_kwargs["aspect_ratio"] = args.aspect_ratio
    if args.size:
        image_config_kwargs["image_size"] = args.size

    if image_config_kwargs:
        kwargs["image_config"] = types.ImageConfig(**image_config_kwargs)

    if args.search or args.image_search:
        search_types = types.SearchTypes(
            web_search=types.WebSearch() if args.search else None,
            image_search=types.ImageSearch() if args.image_search else None,
        )
        kwargs["tools"] = [
            types.Tool(google_search=types.GoogleSearch(search_types=search_types))
        ]

    return types.GenerateContentConfig(**kwargs)


def build_contents(prompt, image_paths):
    contents = [prompt]
    for p in image_paths:
        if str(p).lower().endswith(".svg"):
            try:
                import cairosvg
            except ImportError:
                print(
                    "error: cairosvg is required for SVG input; install with 'pip install cairosvg'",
                    file=sys.stderr,
                )
                sys.exit(1)
            png_bytes = cairosvg.svg2png(url=str(p))
            contents.append(Image.open(io.BytesIO(png_bytes)))
        else:
            contents.append(Image.open(p))
    return contents


def save_images(response, output_dir, ext=None, output=None):
    saved = []
    img_idx = 0

    if output:
        output_path = Path(output)
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        path_ext = output_path.suffix.lstrip(".").lower()
        if path_ext:
            stem = output_path.stem
            suffix = ext or path_ext
        else:
            stem = output_path.name
            suffix = ext or "jpg"
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = ext or "jpg"

    for part in (response.parts or []):
        if part.thought:
            continue
        if part.text is not None:
            print(part.text)
        elif part.inline_data is not None:
            idx_suffix = f"_{img_idx}" if img_idx > 0 else ""
            filename = f"{stem}{idx_suffix}.{suffix}"
            filepath = output_dir / filename
            raw = part.inline_data.data
            image = Image.open(io.BytesIO(raw))
            if suffix in ("jpg", "jpeg"):
                image = image.convert("RGB")
            image.save(filepath)
            saved.append(filepath)
            img_idx += 1

    return saved


def register(subparsers):
    p = subparsers.add_parser("nanobanana", help="generate or edit images via Gemini")
    p.add_argument("prompt", help="text prompt for generation or editing")
    p.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="FILE",
        help="input image(s) for editing (repeatable)",
    )
    p.add_argument(
        "--model",
        default="banana2.1",
        help="model to use (default: banana2.1)",
    )
    p.add_argument(
        "--aspect-ratio",
        choices=ASPECT_RATIOS,
        metavar="RATIO",
        help="output aspect ratio",
    )
    p.add_argument(
        "--size",
        choices=SIZES,
        metavar="SIZE",
        help="output resolution: 1K, 2K, 4K (default: 1K)",
    )
    p.add_argument(
        "--search",
        "--web-search",
        dest="search",
        action="store_true",
        help="enable Google Web Search grounding",
    )
    p.add_argument(
        "--image-search",
        action="store_true",
        help="enable Google Image Search grounding",
    )
    p.add_argument(
        "--thinking",
        action="store_true",
        help="use medium thinking level (default: minimal)",
    )
    p.add_argument(
        "--format",
        choices=["jpg", "png", "webp"],
        default=None,
        help="output image format (default: jpg, or inferred from -o)",
    )
    p.add_argument(
        "--output-dir",
        default="./output",
        help="output directory (default: ./output)",
    )
    p.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="output file path (overrides --output-dir and auto-naming; extension sets format unless --format given)",
    )
    p.add_argument(
        "--backend",
        choices=["vertex", "api"],
        default=os.environ.get("GSKI_NANOBANANA_BACKEND") or "vertex",
        help="backend to use: vertex (default) or api",
    )
    p.set_defaults(func=run)


def _vertex_credentials():
    for c in (
        os.environ.get("GSKI_VERTEX_CREDENTIALS"),
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        VERTEX_CRED_PATH,
    ):
        if c and Path(c).exists():
            return Path(c).resolve()
    return None


def make_client(backend="vertex"):
    if backend == "vertex":
        cred = _vertex_credentials()
        if not cred:
            print(
                f"error: vertex service account json not found at {VERTEX_CRED_PATH}\n"
                "  set GSKI_VERTEX_CREDENTIALS or GOOGLE_APPLICATION_CREDENTIALS",
                file=sys.stderr,
            )
            sys.exit(1)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred)
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            project = json.loads(cred.read_text()).get("project_id")
        if not project:
            print("error: no project_id in credentials; set GOOGLE_CLOUD_PROJECT", file=sys.stderr)
            sys.exit(1)
        return genai.Client(
            vertexai=True,
            project=project,
            location=os.environ.get("GOOGLE_CLOUD_LOCATION") or VERTEX_LOCATION,
            http_options=types.HttpOptions(headers={"Api-Revision": VERTEX_API_REVISION}),
        )

    if not os.environ.get("GEMINI_API_KEY"):
        print("error: GEMINI_API_KEY env var required for api backend", file=sys.stderr)
        sys.exit(1)
    return genai.Client()


def run(args):
    if args.model in PROHIBITED_MODELS:
        print(
            f"error: model '{args.model}' is prohibited. Use Nano Banana 2.1 ('banana2.1').",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.model not in MODELS:
        print(
            f"error: unknown model '{args.model}'. Allowed: {', '.join(MODELS.keys())}",
            file=sys.stderr,
        )
        sys.exit(1)

    for p in args.image:
        if not os.path.isfile(p):
            print(f"error: image not found: {p}", file=sys.stderr)
            sys.exit(1)

    _init_deps()

    client = make_client(args.backend)
    model = MODELS[args.model]
    contents = build_contents(args.prompt, args.image)
    config = build_config(args)

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    saved = save_images(response, args.output_dir, ext=args.format, output=args.output)

    if not saved:
        print("error: no images generated", file=sys.stderr)
        sys.exit(1)

    for path in saved:
        print(path)
