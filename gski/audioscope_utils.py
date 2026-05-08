import subprocess


def probe_duration(path: str) -> float:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr.strip()}")
    return float(r.stdout.strip())


def parse_ts(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) == 2:
        m, sec = parts
        return int(m) * 60 + int(sec)
    if len(parts) == 3:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + int(sec)
    raise ValueError(f"invalid timestamp: {s!r}")


def format_ts(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 0:
        raise ValueError("negative seconds")
    h, rem = divmod(seconds, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def shift_ts(ts: str, offset_sec: int) -> str:
    return format_ts(parse_ts(ts) + offset_sec)
