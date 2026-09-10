import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = (
    Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    / "gski"
    / "omni"
)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def new_job_id():
    return secrets.token_hex(4)


def job_path(job_id):
    return STATE_DIR / f"{job_id}.json"


def video_path_for(job_id):
    return STATE_DIR / f"{job_id}.mp4"


def resolve_job_id(prefix):
    ensure_state_dir()
    matches = sorted(p for p in STATE_DIR.glob("*.json") if p.stem.startswith(prefix))
    if not matches:
        print(f"error: no job matching '{prefix}'", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        ids = ", ".join(p.stem for p in matches)
        print(f"error: ambiguous job id '{prefix}' matches: {ids}", file=sys.stderr)
        sys.exit(1)
    return matches[0].stem


def load_job(prefix):
    job_id = resolve_job_id(prefix)
    return json.loads(job_path(job_id).read_text())


def save_job(job):
    ensure_state_dir()
    job["updated_at"] = now_iso()
    job_path(job["job_id"]).write_text(json.dumps(job, indent=2))


def all_jobs():
    ensure_state_dir()
    jobs = []
    for p in sorted(
        STATE_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True
    ):
        try:
            jobs.append(json.loads(p.read_text()))
        except Exception:
            continue
    return jobs


def new_job(prompt, model, aspect_ratio, resolution, duration=None):
    job_id = new_job_id()
    ts = now_iso()
    job = {
        "job_id": job_id,
        "created_at": ts,
        "updated_at": ts,
        "prompt": prompt,
        "model": model,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "state": "running",
        "interactions": [],
        "current_interaction_id": None,
        "video_path": None,
    }
    if duration:
        job["duration"] = duration
    return job


def record_interaction(job, interaction_id, kind, prompt):
    job["interactions"].append(
        {
            "id": interaction_id,
            "kind": kind,
            "prompt": prompt,
            "created_at": now_iso(),
        }
    )
    job["current_interaction_id"] = interaction_id
    job["state"] = "running"


def remove_job(job, keep_video=False):
    jp = job_path(job["job_id"])
    vp = video_path_for(job["job_id"])
    if jp.exists():
        jp.unlink()
    if vp.exists() and not keep_video:
        vp.unlink()
