import base64
import mimetypes
import re
import sys
import time
from pathlib import Path

from ..deepresearch_lib.api import (
    interactions_create,
    interactions_get,
    make_client,
    new_interaction_id,
)

POLL_INTERVAL = 10
FILE_POLL_INTERVAL = 5


def _read_base64(path):
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def upload_video(client, path):
    p = Path(path)
    if not p.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    f = client.files.upload(file=str(p))
    name = getattr(f, "name", None)
    while getattr(f, "state", None) and str(getattr(f.state, "name", f.state)) == "PROCESSING":
        print(f"[files] processing {name}...", file=sys.stderr)
        time.sleep(FILE_POLL_INTERVAL)
        f = client.files.get(name=name)
    state = str(getattr(getattr(f, "state", None), "name", getattr(f, "state", "")))
    if state == "FAILED":
        print(f"error: video upload processing failed: {name}", file=sys.stderr)
        sys.exit(1)
    uri = getattr(f, "uri", None) or name
    mime = getattr(f, "mime_type", None) or mimetypes.guess_type(str(p))[0] or "video/mp4"
    return uri, mime


def build_input(prompt, images, video, client):
    if not images and not video:
        return prompt

    parts = []
    if video:
        uri, mime = upload_video(client, video)
        parts.append({"type": "document", "uri": uri, "mime_type": mime})
    for img in images:
        p = Path(img)
        if not p.exists():
            print(f"error: image not found: {img}", file=sys.stderr)
            sys.exit(1)
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        parts.append({"type": "image", "data": _read_base64(p), "mime_type": mime})
    parts.append({"type": "text", "text": prompt})
    return parts


def build_response_format(aspect_ratio):
    fmt = {"type": "video", "delivery": "uri"}
    if aspect_ratio:
        fmt["aspect_ratio"] = aspect_ratio
    return fmt


def build_generation_config(task):
    if not task:
        return None
    return {"video_config": {"task": task}}


def poll(client, interaction_id, interval=POLL_INTERVAL):
    start = time.time()
    last_status = None
    while True:
        interaction = interactions_get(client, interaction_id)
        status = getattr(interaction, "status", None)
        if status != last_status:
            elapsed = int(time.time() - start)
            print(f"[{elapsed}s] {status}", file=sys.stderr)
            last_status = status
        if status == "completed":
            return interaction
        if status == "failed":
            err = getattr(interaction, "error", "unknown error")
            print(f"error: generation failed: {err}", file=sys.stderr)
            sys.exit(2)
        time.sleep(interval)


def _part_field(part, field):
    if isinstance(part, dict):
        return part.get(field)
    return getattr(part, field, None)


def extract_video(interaction):
    ov = getattr(interaction, "output_video", None)
    if ov is not None:
        data = getattr(ov, "data", None)
        uri = getattr(ov, "uri", None)
        mime = getattr(ov, "mime_type", None) or "video/mp4"
        if data or uri:
            return data, uri, mime

    steps = getattr(interaction, "steps", None) or []
    for step in steps:
        stype = step.get("type") if isinstance(step, dict) else getattr(step, "type", None)
        if stype != "model_output":
            continue
        content = (
            step.get("content") if isinstance(step, dict) else getattr(step, "content", None)
        )
        parts = content if isinstance(content, (list, tuple)) else [content]
        for part in parts:
            if _part_field(part, "type") == "video":
                data = _part_field(part, "data")
                uri = _part_field(part, "uri")
                mime = _part_field(part, "mime_type") or "video/mp4"
                if data or uri:
                    return data, uri, mime
    return None, None, None


def _file_id_from_uri(uri):
    m = re.search(r"files/([^/:?]+)", uri)
    return m.group(1) if m else None


def download_video(client, data, uri, dest):
    dest = Path(dest)
    if data:
        dest.write_bytes(base64.b64decode(data))
        return dest
    if uri:
        file_id = _file_id_from_uri(uri)
        if file_id:
            while True:
                info = client.files.get(name=f"files/{file_id}")
                state = str(getattr(getattr(info, "state", None), "name", getattr(info, "state", "")))
                if state == "ACTIVE":
                    break
                if state == "FAILED":
                    print("error: video file processing failed", file=sys.stderr)
                    sys.exit(2)
                print(f"[files] {state}...", file=sys.stderr)
                time.sleep(FILE_POLL_INTERVAL)
        video_bytes = client.files.download(file=uri)
        dest.write_bytes(video_bytes)
        return dest
    print("error: no video in response", file=sys.stderr)
    sys.exit(2)
