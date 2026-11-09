import os

from .models import GEMINI_TEXT as MODELS
from .nanoscope_lib.api import (
    DETECT_SUFFIX,
    MEDIA_RESOLUTIONS,
    SEGMENT_SUFFIX,
    TARGET_HEIGHTS,
    build_schemas,
    die,
    extract_text,
    prepare_image_part,
    prepare_video_part,
    run_interaction,
    save_segments,
)


def register(subparsers):
    p = subparsers.add_parser(
        "nanoscope", help="understand and analyze images and videos via Gemini"
    )
    p.add_argument("prompt", help="text prompt or question about the media")
    p.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="FILE",
        help="input image file or URL (repeatable)",
    )
    p.add_argument(
        "--video",
        action="append",
        default=[],
        metavar="FILE",
        help="input video file or URL (repeatable)",
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
        default="3-8",
        help="model: 3-8 (gemini-3.8-flash, default) or argon (gemini-4-argon)",
    )
    p.add_argument(
        "--media-res",
        choices=list(MEDIA_RESOLUTIONS),
        default="low",
        help="API media token resolution: low (default), medium, high, ultra_high",
    )
    p.add_argument(
        "--fps",
        type=float,
        default=1.0,
        help="video frame sampling rate (default: 1.0)",
    )
    p.add_argument(
        "--target-res",
        choices=list(TARGET_HEIGHTS.keys()),
        default="480p",
        help="local video transcode height before upload (default: 480p)",
    )
    p.add_argument(
        "--agentic",
        action="store_true",
        help="use agentic video processing instead of static",
    )
    p.add_argument(
        "--no-audio",
        action="store_true",
        help="strip audio track when transcoding local video (default: keep audio)",
    )
    p.add_argument(
        "--start",
        metavar="TIME",
        help="video clip start offset for static mode (e.g. 1200 or 20:00)",
    )
    p.add_argument(
        "--end",
        metavar="TIME",
        help="video clip end offset for static mode (e.g. 1500 or 25:00)",
    )
    p.add_argument(
        "--detect",
        action="store_true",
        help="object detection mode (JSON bounding boxes)",
    )
    p.add_argument(
        "--segment",
        action="store_true",
        help="segmentation mode (polygon mask + overlay PNGs)",
    )
    p.add_argument(
        "--output-dir",
        default="./output",
        help="output directory for segmentation (default: ./output)",
    )
    p.set_defaults(func=run)


def run(args):
    if args.detect and args.segment:
        die("--detect and --segment are mutually exclusive")

    images = list(args.image) + list(args.url)
    videos = list(args.video)

    if not images and not videos:
        die("provide at least one --image, --video, or --url")

    if (args.detect or args.segment) and videos:
        die("--detect and --segment only support --image inputs")

    if args.segment and not args.image:
        die("--segment requires at least one local --image file")

    if args.agentic and (args.start is not None or args.end is not None):
        die("--start and --end are only supported in static mode (omit --agentic)")

    if not os.environ.get("GEMINI_API_KEY"):
        die("GEMINI_API_KEY env var required")

    from google import genai
    from google.genai import types

    prompt = args.prompt
    if args.detect:
        prompt += DETECT_SUFFIX
    elif args.segment:
        prompt += SEGMENT_SUFFIX

    # Docs: for video, place text prompt AFTER video; for image-only, place text BEFORE images.
    parts = []
    if not videos:
        parts.append({"type": "text", "text": prompt})
        for img in images:
            parts.append(prepare_image_part(img, args.media_res))
    else:
        for vid in videos:
            parts.append(prepare_video_part(vid, args))
        for img in images:
            parts.append(prepare_image_part(img, args.media_res))
        parts.append({"type": "text", "text": prompt})

    kwargs = {
        "model": MODELS[args.model],
        "input": parts,
    }

    if args.detect or args.segment:
        kwargs["response_format"] = {
            "type": "text",
            "mime_type": "application/json",
            "schema": build_schemas(segment=args.segment),
        }
    if args.segment:
        kwargs["generation_config"] = {"thinking_level": "low"}

    client = genai.Client(http_options=types.HttpOptions(api_version="v1beta"))
    interaction = run_interaction(client, kwargs, is_video=bool(videos))
    text = extract_text(interaction)

    if args.segment:
        saved = save_segments(text, args.image[0], args.output_dir)
        if not saved:
            die("no segmentation masks produced")
        for path in saved:
            print(path)
    else:
        print(text)
