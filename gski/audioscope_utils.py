import subprocess
from dataclasses import dataclass


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


@dataclass(frozen=True)
class ChunkSpec:
    index: int
    start: int
    end: int

    @property
    def duration(self) -> int:
        return self.end - self.start


def plan_chunks(
    duration_sec: float,
    chunk_len_sec: int = 900,
    overlap_sec: int = 30,
    min_chunk_sec: int = 60,
) -> list[ChunkSpec]:
    duration_sec = int(duration_sec)
    if duration_sec <= chunk_len_sec:
        return [ChunkSpec(index=0, start=0, end=duration_sec)]

    stride = chunk_len_sec - overlap_sec
    if stride <= 0:
        raise ValueError("overlap must be smaller than chunk length")

    chunks: list[ChunkSpec] = []
    i = 0
    start = 0
    while start < duration_sec:
        end = min(start + chunk_len_sec, duration_sec)
        chunks.append(ChunkSpec(index=i, start=start, end=end))
        if end >= duration_sec:
            break
        start += stride
        i += 1

    if len(chunks) >= 2 and chunks[-1].duration < min_chunk_sec:
        prev = chunks[-2]
        last = chunks[-1]
        chunks[-2] = ChunkSpec(prev.index, prev.start, last.end)
        chunks.pop()
        chunks = [ChunkSpec(i, c.start, c.end) for i, c in enumerate(chunks)]

    return chunks


def extract_chunk(src: str, dest: str, start_sec: int, end_sec: int) -> None:
    r = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
            "-ss", str(start_sec),
            "-to", str(end_sec),
            "-i", str(src),
            "-vn",
            "-c:a", "libopus", "-b:a", "48k",
            str(dest),
        ],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg chunk extract failed: {r.stderr.strip()}")


def extract_chunk_with_offset(
    src: str, dest: str, *, start: int, end: int, offset_sec: int,
) -> None:
    """Extract [start+offset .. end] — shifts only start, preserves end.

    Used for retry when the model skipped content at the beginning of a chunk.
    If offset leaves less than 60s of audio, falls back to regular extraction
    so the retry still sees a usable chunk.
    """
    actual_start = start + offset_sec
    actual_dur = end - actual_start
    if actual_dur < 60:
        extract_chunk(src, dest, start, end)
        return
    r = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
            "-ss", str(actual_start),
            "-t", str(actual_dur),
            "-i", str(src),
            "-vn",
            "-c:a", "libopus", "-b:a", "48k",
            str(dest),
        ],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg chunk extract (offset) failed: {r.stderr.strip()}"
        )
