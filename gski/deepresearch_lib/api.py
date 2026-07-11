import mimetypes
import os
import re
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore", message=r".*Interactions usage is experimental.*"
)

from google import genai

from ..models import GEMINI_DEEP_RESEARCH as AGENT_MODELS

POLL_INTERVAL = 10


def make_client():
    if not os.environ.get("GEMINI_API_KEY"):
        print("error: GEMINI_API_KEY env var required", file=sys.stderr)
        sys.exit(1)
    return genai.Client()


def _interactions(client):
    api = getattr(client, "interactions", None)
    if api is None:
        print(
            "error: this google-genai version has no `interactions` API.\n"
            "  try: pip install -U google-genai",
            file=sys.stderr,
        )
        sys.exit(1)
    return api


def interactions_create(client, **kwargs):
    return _interactions(client).create(**kwargs)


def interactions_get(client, interaction_id):
    return _interactions(client).get(interaction_id)


def upload_file(client, path):
    p = Path(path)
    if not p.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    f = client.files.upload(file=str(p))
    uri = getattr(f, "uri", None) or getattr(f, "name", None)
    if not uri:
        print(f"error: upload of {path} returned no uri", file=sys.stderr)
        sys.exit(1)
    mime = getattr(f, "mime_type", None)
    if not mime:
        mime, _ = mimetypes.guess_type(str(p))
    return uri, mime


def build_input(prompt, files, client):
    if not files:
        return prompt

    parts = [{"type": "text", "text": prompt}]
    for item in files:
        if re.match(r"^https?://", item):
            mime, _ = mimetypes.guess_type(item)
            uri = item
        else:
            uri, mime = upload_file(client, item)
        kind = "image" if (mime and mime.startswith("image/")) else "document"
        part = {"type": kind, "uri": uri}
        if mime:
            part["mime_type"] = mime
        parts.append(part)
    return parts


def _part_text(part):
    if part is None:
        return None
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        return part.get("text")
    return getattr(part, "text", None)


def _step_text(step):
    """Pull text from a step's `content`, which may be a string, a part, or a
    list of parts."""
    content = (
        step.get("content") if isinstance(step, dict) else getattr(step, "content", None)
    )
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = content if isinstance(content, (list, tuple)) else [content]
    return "\n\n".join(t for t in (_part_text(p) for p in parts) if t)


def extract_text(interaction):
    # New schema: full report is assembled from `steps[].content` parts.
    steps = getattr(interaction, "steps", None) or []
    chunks = [t for t in (_step_text(s) for s in steps) if t]
    if chunks:
        return "\n\n".join(chunks)

    # Newer single-field fallback.
    output_text = getattr(interaction, "output_text", None)
    if output_text:
        return output_text

    # Legacy schema: `outputs` list of text parts.
    outputs = getattr(interaction, "outputs", None) or []
    legacy = []
    for out in outputs:
        text = getattr(out, "text", None)
        otype = getattr(out, "type", None)
        if text is None and isinstance(out, dict):
            text = out.get("text")
            otype = out.get("type")
        if text and (otype is None or otype == "text"):
            legacy.append(text)
    if legacy:
        return "".join(legacy)

    return getattr(interaction, "text", "") or ""


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
            print(f"error: research failed: {err}", file=sys.stderr)
            sys.exit(2)
        time.sleep(interval)


def new_interaction_id(interaction):
    iid = getattr(interaction, "id", None)
    if not iid:
        print("error: api returned no interaction id", file=sys.stderr)
        sys.exit(1)
    return iid
