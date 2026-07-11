import base64
import io
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from .models import OPENAI_IMAGE as MODELS

POPULAR_SIZES = [
    "auto",
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "2048x2048",
    "2048x1152",
    "3840x2160",
    "2160x3840",
]

SIZE_RE = re.compile(r"^\d+x\d+$|^auto$")


def validate_size(value):
    if not SIZE_RE.match(value):
        raise SystemExit(f"error: invalid --size {value!r}; use WxH or 'auto'")
    return value


PIL_FORMAT = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}


def save_b64_images(data_items, output_dir, ext, compression=None):
    from PIL import Image

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = PIL_FORMAT[ext]
    saved = []
    for i, b64 in enumerate(data_items):
        suffix = f"_{i}" if i > 0 else ""
        filepath = output_dir / f"{ts}{suffix}.{ext}"
        raw = base64.b64decode(b64)
        img = Image.open(io.BytesIO(raw))
        save_kwargs = {}
        if target == "JPEG":
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            save_kwargs["quality"] = compression if compression is not None else 90
        elif target == "WEBP":
            if compression is not None:
                save_kwargs["quality"] = compression
        img.save(filepath, format=target, **save_kwargs)
        saved.append(filepath)
    return saved


def register(subparsers):
    p = subparsers.add_parser(
        "gptimage2", help="generate or edit images via OpenAI GPT Image"
    )
    p.add_argument("prompt", help="text prompt for generation or editing")
    p.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="FILE",
        help="input image(s) for editing (repeatable)",
    )
    p.add_argument(
        "--mask",
        metavar="FILE",
        help="optional mask image (applies to first --image)",
    )
    p.add_argument(
        "--model",
        choices=MODELS,
        default="gpt-image-2",
        help="model to use (default: gpt-image-2)",
    )
    p.add_argument(
        "--size",
        default="auto",
        metavar="SIZE",
        help=f"output size WxH or auto (popular: {', '.join(POPULAR_SIZES)})",
    )
    p.add_argument(
        "--quality",
        choices=["auto", "low", "medium", "high"],
        default="auto",
        help="rendering quality (default: auto)",
    )
    p.add_argument(
        "--format",
        choices=["jpg", "png", "webp"],
        default="jpg",
        help="output image format (default: jpg)",
    )
    p.add_argument(
        "--compression",
        type=int,
        metavar="0-100",
        help="compression level for jpeg/webp",
    )
    p.add_argument(
        "--background",
        choices=["auto", "opaque"],
        default="auto",
        help="background handling (default: auto)",
    )
    p.add_argument(
        "-n",
        "--n",
        type=int,
        default=1,
        help="number of images (default: 1)",
    )
    p.add_argument(
        "--output-dir",
        default="./output",
        help="output directory (default: ./output)",
    )
    p.set_defaults(func=run)


def run(args):
    validate_size(args.size)

    for p in args.image:
        if not os.path.isfile(p):
            print(f"error: image not found: {p}", file=sys.stderr)
            sys.exit(1)

    if args.mask and not os.path.isfile(args.mask):
        print(f"error: mask not found: {args.mask}", file=sys.stderr)
        sys.exit(1)

    if args.mask and not args.image:
        print("error: --mask requires --image", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("OPENAI_API_KEY"):
        print("error: OPENAI_API_KEY env var required", file=sys.stderr)
        sys.exit(1)

    try:
        from openai import OpenAI
    except ImportError:
        print(
            "error: openai is required; install with 'pip install openai'",
            file=sys.stderr,
        )
        sys.exit(1)

    client = OpenAI()

    api_format = {"jpg": "jpeg", "png": "png", "webp": "webp"}[args.format]

    common = {
        "model": args.model,
        "prompt": args.prompt,
        "n": args.n,
        "size": args.size,
        "quality": args.quality,
        "background": args.background,
        "output_format": api_format,
    }

    if args.compression is not None:
        if args.format not in ("jpg", "webp"):
            print("error: --compression only valid for jpg/webp", file=sys.stderr)
            sys.exit(1)
        common["output_compression"] = args.compression

    image_files = []
    mask_file = None
    try:
        if args.image:
            image_files = [open(p, "rb") for p in args.image]
            edit_kwargs = dict(common)
            edit_kwargs["image"] = image_files if len(image_files) > 1 else image_files[0]
            if args.mask:
                mask_file = open(args.mask, "rb")
                edit_kwargs["mask"] = mask_file
            result = client.images.edit(**edit_kwargs)
        else:
            result = client.images.generate(moderation="low", **common)
    finally:
        for f in image_files:
            f.close()
        if mask_file:
            mask_file.close()

    data_items = [d.b64_json for d in result.data if d.b64_json]
    if not data_items:
        print("error: no images returned", file=sys.stderr)
        sys.exit(1)

    saved = save_b64_images(
        data_items, args.output_dir, ext=args.format, compression=args.compression
    )
    for path in saved:
        print(path)
