import base64
from datetime import datetime
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List
import urllib.error
import urllib.parse
import urllib.request
import warnings

warnings.filterwarnings("ignore", message=r".*Interactions usage is experimental.*")

BUCKET = os.environ.get("GSKI_GCS_BUCKET") or "gemini-20241009-bdsd-refs"
TARGET_HEIGHTS = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080, "original": None}
MEDIA_RESOLUTIONS = ("low", "medium", "high", "ultra_high")
DETECT_SUFFIX = " The box_2d should be [ymin, xmin, ymax, xmax] normalized to 0-1000."
SEGMENT_SUFFIX = (
    ' Output a JSON list of segmentation masks where each entry contains the 2D'
    ' bounding box in the key "box_2d", the segmentation mask in key "mask", and'
    ' the text label in the key "label". Use descriptive labels.'
)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def is_url(val):
    return bool(re.match(r"^https?://", str(val)))


def parse_offset(val):
    if val is None:
        return None
    s = str(val).strip()
    if s.endswith("s"):
        s = s[:-1].strip()
    if ":" in s:
        secs = 0.0
        for part in s.split(":"):
            secs = secs * 60.0 + float(part)
        return f"{secs:g}s"
    return f"{float(s):g}s"


def fmt_dur(seconds):
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def file_sha1_prefix(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha1").hexdigest()[:12]


def bucket_url(obj):
    return f"https://storage.googleapis.com/{BUCKET}/{urllib.parse.quote(obj)}"


def bucket_exists(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False


def upload_to_bucket(local_path, obj):
    url = bucket_url(obj)
    if bucket_exists(url):
        log(f"[upload] cached {url}")
        return url
    if not shutil.which("gcloud"):
        die("gcloud CLI not found in PATH for bucket upload")
    size_mb = Path(local_path).stat().st_size / (1024 * 1024)
    t0 = time.time()
    log(f"[upload] {size_mb:.1f}MB -> gs://{BUCKET}/{obj}")
    cp = subprocess.run(
        ["gcloud", "storage", "cp", str(local_path), f"gs://{BUCKET}/{obj}"],
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0:
        die(f"upload failed: {cp.stderr.strip()[:300]}")
    log(f"[upload] done ({time.time() - t0:.1f}s)")
    return url


def ffprobe_duration(path):
    if not shutil.which("ffprobe"):
        die("ffprobe not found in PATH")
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    return float(out.decode().strip() or 0.0)


def _has_vaapi():
    return Path("/dev/dri/renderD128").exists()


def _build_ffmpeg_cmd(src, dst, height, fps, keep_audio, use_vaapi):
    cmd = ["ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1"]
    if fps and fps <= 5:
        cmd += ["-skip_frame", "noref"]
    if use_vaapi:
        cmd += ["-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128", "-hwaccel_output_format", "vaapi"]
    cmd += ["-i", str(src)]
    vf = []
    if fps:
        vf.append(f"fps={fps:g}")
    if use_vaapi:
        vf.append(f"scale_vaapi=w=-2:h='min({height},ih)':format=nv12" if height else "scale_vaapi=format=nv12")
    elif height:
        vf.append(f"scale=-2:'min({height},ih)'")
    if vf:
        cmd += ["-vf", ",".join(vf)]
    if use_vaapi:
        cmd += ["-c:v", "h264_vaapi", "-qp", "30"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p"]
    if keep_audio:
        cmd += ["-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "24k"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(dst)]
    return cmd


def transcode_video(src, dst, height, fps, keep_audio):
    if not shutil.which("ffmpeg"):
        die("ffmpeg not found in PATH")
    total = ffprobe_duration(src)
    use_vaapi = _has_vaapi()
    for attempt_vaapi in ([True, False] if use_vaapi else [False]):
        cmd = _build_ffmpeg_cmd(src, dst, height, fps, keep_audio, attempt_vaapi)
        t0 = time.time()
        next_pct = 10
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            if total > 0 and line.startswith("out_time_us="):
                val = line.split("=", 1)[1].strip()
                if val.lstrip("-").isdigit():
                    cur = max(0.0, int(val) / 1_000_000.0)
                    pct = min(100, int(cur * 100.0 / total))
                    if pct >= next_pct and pct < 100:
                        ms = (pct // 10) * 10
                        log(f"[transcode] {ms}% ({fmt_dur(cur)}/{fmt_dur(total)}, {int(time.time() - t0)}s)")
                        next_pct = ms + 10
        _, err = proc.communicate()
        if proc.returncode == 0:
            size_mb = Path(dst).stat().st_size / (1024 * 1024)
            log(f"[transcode] 100% ({fmt_dur(total)}/{fmt_dur(total)}, {time.time() - t0:.1f}s, {size_mb:.1f}MB)")
            return
        if not attempt_vaapi:
            die(f"ffmpeg failed: {err.strip()[:300]}")


def _already_transcoded(path, height, fps, keep_audio):
    if Path(path).suffix.lower() != ".mp4" or not keep_audio:
        return False
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=height,r_frame_rate",
                "-of",
                "csv=p=0",
                str(path),
            ],
            text=True,
        ).strip()
        h_str, fps_str = out.split(",", 1)
        cur_h = int(h_str)
        num, den = (fps_str.split("/", 1) + ["1"])[:2]
        cur_fps = float(num) / float(den)
        return (height is None or cur_h <= height) and (fps is None or cur_fps <= fps + 0.05)
    except Exception:
        return False


def find_cached_file(obj):
    from google import genai
    from google.genai import types

    client = genai.Client(http_options=types.HttpOptions(api_version="v1beta"))
    for f in client.files.list():
        if getattr(f, "display_name", None) == obj:
            while f.state and f.state.name == "PROCESSING":
                time.sleep(2)
                f = client.files.get(name=f.name)
            if f.state and f.state.name == "ACTIVE":
                log(f"[files] cached {f.uri}")
                return f.uri
    return None


def upload_to_files_api(local_path, obj, mime="video/mp4"):
    cached = find_cached_file(obj)
    if cached:
        return cached
    from google import genai
    from google.genai import types

    client = genai.Client(http_options=types.HttpOptions(api_version="v1beta"))
    size_mb = Path(local_path).stat().st_size / (1024 * 1024)
    t0 = time.time()
    log(f"[files] uploading {size_mb:.1f}MB ({obj})...")
    f = client.files.upload(file=str(local_path), config={"display_name": obj, "mime_type": mime})
    while f.state and f.state.name == "PROCESSING":
        time.sleep(3)
        f = client.files.get(name=f.name)
    if not f.state or f.state.name != "ACTIVE":
        die(f"file processing failed: {getattr(f, 'state', None)}")
    log(f"[files] ready {f.uri} ({time.time() - t0:.1f}s)")
    return f.uri


def prepare_video_url(path, target_res, fps, keep_audio):
    if is_url(path):
        return path, "video/mp4"
    p = Path(path)
    if not p.is_file():
        die(f"video not found: {path}")
    h = file_sha1_prefix(p)
    safe_stem = re.sub(r"[^\w.\-]", "_", p.stem)
    height = TARGET_HEIGHTS[target_res]
    if height is None and keep_audio and fps is None:
        obj = f"{h}-{re.sub(r'[^\w.\-]', '_', p.name)}"
        mime = mimetypes.guess_type(str(p))[0] or "video/mp4"
        return upload_to_files_api(p, obj, mime), mime

    tag = f"{target_res}_{fps:g}fps_{'a1' if keep_audio else 'a0'}"
    obj = f"{h}-{safe_stem}_{tag}.mp4"
    cached = find_cached_file(obj)
    if cached:
        return cached, "video/mp4"

    if _already_transcoded(p, height, fps, keep_audio):
        return upload_to_files_api(p, obj, "video/mp4"), "video/mp4"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / obj
        transcode_video(p, out, height, fps, keep_audio)
        return upload_to_files_api(out, obj, "video/mp4"), "video/mp4"


def prepare_image_part(path_or_url, media_res):
    if is_url(path_or_url):
        mime = mimetypes.guess_type(path_or_url)[0] or "image/jpeg"
        part = {"type": "image", "uri": path_or_url, "mime_type": mime}
    else:
        p = Path(path_or_url)
        if not p.is_file():
            die(f"image not found: {path_or_url}")
        mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
        if p.stat().st_size > 10 * 1024 * 1024:
            h = file_sha1_prefix(p)
            obj = f"{h}-{re.sub(r'[^\w.\-]', '_', p.name)}"
            part = {"type": "image", "uri": upload_to_bucket(p, obj), "mime_type": mime}
        else:
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            part = {"type": "image", "data": b64, "mime_type": mime}
    if media_res:
        part["resolution"] = media_res
    return part


def prepare_video_part(path_or_url, args):
    url, mime = prepare_video_url(path_or_url, args.target_res, args.fps, not args.no_audio)
    part = {"type": "video", "uri": url}
    if not re.search(r"(youtube\.com|youtu\.be)/", url):
        part["mime_type"] = mime
    if args.media_res:
        part["resolution"] = args.media_res
    if args.agentic:
        part["processing"] = "agentic"
    else:
        proc = {"type": "static", "fps": args.fps}
        if args.start is not None:
            proc["start_offset"] = parse_offset(args.start)
        if args.end is not None:
            proc["end_offset"] = parse_offset(args.end)
        part["processing"] = proc
    return part


def build_schemas(segment=False):
    from pydantic import BaseModel, Field

    if segment:
        class BoundingBox(BaseModel):
            box_2d: List[int] = Field(description="The 2D bounding box as [ymin, xmin, ymax, xmax] normalized to 0-1000.")
            mask: List[List[int]] = Field(description="The segmentation mask polygon coordinates normalized to 0-1000.")
            label: str = Field(description="A descriptive label for the item.")
    else:
        class BoundingBox(BaseModel):
            box_2d: List[int] = Field(description="The 2D bounding box as [ymin, xmin, ymax, xmax] normalized to 0-1000.")
            label: str = Field(description="A descriptive label for the item.")

    class BoundingBoxes(BaseModel):
        boxes: List[BoundingBox]

    return BoundingBoxes.model_json_schema()


def extract_text(interaction):
    if getattr(interaction, "output_text", None):
        return interaction.output_text
    chunks = []
    for s in getattr(interaction, "steps", None) or []:
        if getattr(s, "type", None) == "model_output":
            for c in getattr(s, "content", None) or []:
                t = getattr(c, "text", None)
                if t:
                    chunks.append(t)
    return "\n".join(chunks)


def run_interaction(client, kwargs, is_video):
    if not is_video:
        return client.interactions.create(**kwargs)
    t0 = time.time()
    inter = client.interactions.create(background=True, **kwargs)
    iid = inter.id
    last_steps = 0
    last_log = t0
    log(f"[gemini] started ({ kwargs['model'] })")
    while inter.status == "in_progress":
        time.sleep(4)
        inter = client.interactions.get(iid)
        steps = len(getattr(inter, "steps", None) or [])
        now = time.time()
        if (steps > last_steps and now - last_log >= 8) or (now - last_log >= 25):
            log(f"[gemini] in_progress ({int(now - t0)}s, steps={steps})")
            last_steps = steps
            last_log = now
    if inter.status == "failed":
        die(f"interaction failed: {getattr(inter, 'error', 'unknown error')}")
    log(f"[gemini] done ({time.time() - t0:.1f}s)")
    return inter


def _poly_to_xy(pts, box, size):
    w, h = size
    ymin, xmin, ymax, xmax = box
    err_yx = sum(max(0, ymin - p[0], p[0] - ymax) + max(0, xmin - p[1], p[1] - xmax) for p in pts if len(p) >= 2)
    err_xy = sum(max(0, xmin - p[0], p[0] - xmax) + max(0, ymin - p[1], p[1] - ymax) for p in pts if len(p) >= 2)
    is_yx = err_yx <= err_xy
    out = []
    for p in pts:
        if len(p) < 2:
            continue
        ny, nx = (p[0], p[1]) if is_yx else (p[1], p[0])
        out.append((int(nx / 1000.0 * w), int(ny / 1000.0 * h)))
    return out


def save_segments(raw_text, image_path, output_dir):
    from PIL import Image, ImageDraw

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    im = Image.open(image_path).convert("RGBA")
    w, h = im.size

    data = json.loads(raw_text)
    items = data.get("boxes", data) if isinstance(data, dict) else data
    saved = []

    for i, item in enumerate(items):
        box = item.get("box_2d") or [0, 0, 1000, 1000]
        pts = item.get("mask") or []
        if len(pts) < 3:
            continue
        xy = _poly_to_xy(pts, box, (w, h))
        if len(xy) < 3:
            continue

        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).polygon(xy, fill=255)

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(overlay).polygon(xy, fill=(255, 255, 255, 180), outline=(255, 255, 255, 255))

        label = re.sub(r"[^\w\-]+", "_", item.get("label", f"mask_{i}")).strip("_") or f"mask_{i}"
        mask_path = out_dir / f"{ts}_{label}_{i}_mask.png"
        overlay_path = out_dir / f"{ts}_{label}_{i}_overlay.png"

        mask.save(mask_path)
        Image.alpha_composite(im, overlay).save(overlay_path)
        saved.extend((mask_path, overlay_path))

    return saved
