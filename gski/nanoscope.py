import base64
import io
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np
from google import genai
from google.genai import types
from PIL import Image, ImageDraw


MODELS = {
    "flash": "gemini-3.5-flash",
    "pro": "gemini-3.1-pro-preview",
}

DETECT_SUFFIX = " The box_2d should be [ymin, xmin, ymax, xmax] normalized to 0-1000."


def build_config(args):
    kwargs = {}

    if args.detect:
        kwargs["response_mime_type"] = "application/json"

    if args.segment:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

    if not kwargs:
        return None
    return types.GenerateContentConfig(**kwargs)


def build_contents(prompt, image_paths, urls):
    contents = []

    for p in image_paths:
        contents.append(Image.open(p))

    for url in urls:
        req = urllib.request.Request(url, headers={"User-Agent": "nanoscope/1.0"})
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
            content_type = resp.headers.get_content_type() or "image/jpeg"
        contents.append(types.Part.from_bytes(data=data, mime_type=content_type))

    contents.append(prompt)
    return contents


def parse_json(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "```json":
            rest = "\n".join(lines[i + 1 :])
            return rest.split("```")[0]
    return text


def run_segment(response, images, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    im = images[0].copy()
    im.thumbnail([1024, 1024], Image.Resampling.LANCZOS)

    items = json.loads(parse_json(response.text))
    saved = []

    for i, item in enumerate(items):
        box = item["box_2d"]
        y0 = int(box[0] / 1000 * im.size[1])
        x0 = int(box[1] / 1000 * im.size[0])
        y1 = int(box[2] / 1000 * im.size[1])
        x1 = int(box[3] / 1000 * im.size[0])

        if y0 >= y1 or x0 >= x1:
            continue

        png_str = item.get("mask", "")
        if not png_str.startswith("data:image/png;base64,"):
            continue

        png_str = png_str.removeprefix("data:image/png;base64,")
        mask_data = base64.b64decode(png_str)
        mask = Image.open(io.BytesIO(mask_data))
        mask = mask.resize((x1 - x0, y1 - y0), Image.Resampling.BILINEAR)

        mask_array = np.array(mask)

        overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        color = (255, 255, 255, 200)
        for y in range(y0, y1):
            for x in range(x0, x1):
                if mask_array[y - y0, x - x0] > 128:
                    overlay_draw.point((x, y), fill=color)

        label = item.get("label", f"mask_{i}")
        safe_label = label.replace(" ", "_").replace("/", "_")

        mask_path = output_dir / f"{ts}_{safe_label}_{i}_mask.png"
        overlay_path = output_dir / f"{ts}_{safe_label}_{i}_overlay.png"

        mask.save(mask_path)
        composite = Image.alpha_composite(im.convert("RGBA"), overlay)
        composite.save(overlay_path)

        saved.append(mask_path)
        saved.append(overlay_path)

    return saved


def register(subparsers):
    p = subparsers.add_parser(
        "nanoscope", help="understand and analyze images via Gemini"
    )
    p.add_argument("prompt", help="text prompt or question about the image(s)")
    p.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="FILE",
        help="input image file (repeatable)",
    )
    p.add_argument(
        "--url",
        action="append",
        default=[],
        metavar="URL",
        help="input image URL (repeatable)",
    )
    p.add_argument(
        "--model",
        choices=list(MODELS.keys()),
        default="flash",
        help="model to use (default: flash)",
    )
    p.add_argument(
        "--detect",
        action="store_true",
        help="object detection mode (JSON bounding boxes)",
    )
    p.add_argument(
        "--segment",
        action="store_true",
        help="segmentation mode (mask + overlay PNGs)",
    )
    p.add_argument(
        "--output-dir",
        default="./output",
        help="output directory for segmentation (default: ./output)",
    )
    p.set_defaults(func=run)


def run(args):
    if args.detect and args.segment:
        print("error: --detect and --segment are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if not args.image and not args.url:
        print("error: at least one --image or --url required", file=sys.stderr)
        sys.exit(1)

    for p in args.image:
        if not os.path.isfile(p):
            print(f"error: image not found: {p}", file=sys.stderr)
            sys.exit(1)

    if not os.environ.get("GEMINI_API_KEY"):
        print("error: GEMINI_API_KEY env var required", file=sys.stderr)
        sys.exit(1)

    prompt = args.prompt
    if args.detect:
        prompt += DETECT_SUFFIX

    images = [Image.open(p) for p in args.image]

    if args.segment and images:
        for im in images:
            im.thumbnail([1024, 1024], Image.Resampling.LANCZOS)

    client = genai.Client()
    model = MODELS[args.model]
    contents = build_contents(prompt, args.image, args.url)
    config = build_config(args)

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    if args.segment:
        if not images:
            print(
                "error: --segment requires at least one --image (local file)",
                file=sys.stderr,
            )
            sys.exit(1)
        saved = run_segment(response, images, args.output_dir)
        if not saved:
            print("error: no segmentation masks produced", file=sys.stderr)
            sys.exit(1)
        for path in saved:
            print(path)
    else:
        print(response.text)
