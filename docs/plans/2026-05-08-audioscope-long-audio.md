# Audioscope Long-Audio Fix Implementation Plan

> **For executor:** Use the `executing-plans` skill (or `subagent-driven-development`) to implement this plan task-by-task.

**Goal:** Make `gski audioscope --diarize --timestamps` reliably transcribe 1–3h Russian Google Meet recordings without middle-skip, infinite loops, or `MAX_TOKENS` JSON truncation.

**Architecture:**
- Detect long audio (`duration > --chunk-threshold`, default 20 min) → split with ffmpeg into 15-min chunks with 30s overlap → transcribe each chunk sequentially with Gemini Flash (context injection from previous chunk's tail) → validate each chunk (duration/loop/gap gates) with automatic retry → merge overlapping segments with global timestamp offsets → emit single unified JSON+text.
- Short audio path remains single-shot (current behaviour), just gets `generationConfig` hardening and flat schema.
- **Not in this PR (tracked as TODO):** pyannote hybrid diarization, parallel chunk processing, LLM-as-judge validator, Deepgram/ElevenLabs fallback.

**Tech Stack:**
- Python 3.10+, `google-genai` SDK (already a dep)
- `ffmpeg` / `ffprobe` (system binaries, shell out via `subprocess`)
- stdlib `difflib.SequenceMatcher` for overlap dedup (no new deps)
- `pytest` for tests (add to pyproject dev-deps)

**Anchor facts from deep-research** (`notes/projects/google-meet-transcribe/long-audio-gemini-sota-research`):
- Root causes: rank collapse (middle-skip), repetition collapse (loop), shared thinking/output budget (MAX_TOKENS).
- Chunk 15 min + 30s overlap is evidence-based sweet spot for Gemini.
- Flash > Pro for transcription (Pro falls into reasoning loops on audio; Flash doesn't).
- Gen config: `temperature=0, top_p=0, top_k=1, candidate_count=1, seed=42, thinking_budget=0`.
- Flat JSON with single-letter keys reduces structural tokens ~70%.
- Duration-mismatch threshold `> 60s` = truncation signal. 5-gram repeat >4× = loop.

---

## Task 0: Baseline — ensure worktree runs

**Files:**
- None (setup only)

**Step 1: Install package editable**
```bash
cd /Users/iz/work/gski/.worktrees/audioscope-long-audio
pip install -e .
```
Expected: installs `gski` from worktree without errors.

**Step 2: Add dev deps to `pyproject.toml`**

Edit `pyproject.toml`, in `[project]` add:
```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12"]
```

**Step 3: Install dev deps**
```bash
pip install -e ".[dev]"
```

**Step 4: Verify ffmpeg/ffprobe present**
```bash
which ffmpeg ffprobe
```
Expected: both paths printed. If missing → `brew install ffmpeg`.

**Step 5: Smoke-run current audioscope against small file**
```bash
gski audioscope --audio /Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-08.ogg --diarize --timestamps --model flash --output-dir /tmp/audioscope-baseline 2>&1 | head -20
```
Expected: either runs or MAX_TOKENS failure we're about to fix. Either way, not crashing on import.

**Step 6: Commit setup**
```bash
git add pyproject.toml
git commit -m "audioscope: add pytest dev deps"
```

---

## Task 1: Fetch missing test fixture (2.5h loop file from 2026-05-07)

**Files:**
- Download to: `/Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-07.ogg`

**Context:** Research notes reference a 2.5h Meet that triggered the loop failure (2026-05-07 daily operational sync). We need it as regression fixture. The `meet-transcribe` script knows how to pull from Drive via `gwsa work drive` subcommands.

**Step 1: List available recordings**
```bash
/Users/iz/work/scripts/meet-transcribe --list 2>&1 | head -30
```
Expected: table with recent recordings including date 2026-05-07.

**Step 2: Find file id for 2026-05-07**

Option A — use meet-transcribe's `--date`:
```bash
/Users/iz/work/scripts/meet-transcribe --date 2026-05-07 --list 2>&1
```

Option B — raw Drive query (if `--list` doesn't show ids):
```bash
gwsa work drive files list --params '{"pageSize":50,"q":"\u00271jfFP3HxDzNKMi6xnvlPQGtVdzOS7Oi5K\u0027 in parents and mimeType = \u0027video/mp4\u0027","orderBy":"createdTime desc","fields":"files(id,name,size,createdTime)"}' | jq '.files[] | select(.name | contains("2026/05/07"))'
```

**Step 3: Download mp4 to /tmp**
```bash
FILE_ID="<id from step 2>"
gwsa work drive files get --params "{\"fileId\":\"$FILE_ID\",\"alt\":\"media\"}" --output /tmp/meet-05-07.mp4
```
Expected: mp4 file (likely 500MB–1.5GB for 2.5h).

**Step 4: Extract OGG/Opus audio**
```bash
ffmpeg -i /tmp/meet-05-07.mp4 -vn -acodec libopus -b:a 48k /Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-07.ogg -y
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 /Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-07.ogg
```
Expected: duration ≈ 9000s (2.5h). Delete /tmp mp4 after.

**Step 5: Verify fixture size**
```bash
ls -lh /Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-0{7,8}.ogg
```
Expected: ~45–60 MB for 05-07, ~39 MB for 05-08.

**Step 6: Do NOT commit audio** — too big, not in repo. These live outside the gski repo, under `tasks/google-meet-transcribe/tests/`. The gski tests reference them via absolute path (acceptable for this repo; fixtures are on dev machines only).

---

## Task 2: Extract a `probe_duration` helper

**Files:**
- Create: `gski/audioscope_utils.py`
- Test: `tests/test_audioscope_utils.py`

**Rationale:** We'll need `ffprobe` in several places (splitter, validator). Isolate it in a util.

**Step 1: Write failing test**

Create `tests/__init__.py` (empty) and `tests/test_audioscope_utils.py`:
```python
import subprocess
from unittest.mock import patch

from gski.audioscope_utils import probe_duration


def test_probe_duration_parses_float():
    fake_run = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="7523.456\n", stderr=""
    )
    with patch("gski.audioscope_utils.subprocess.run", return_value=fake_run):
        assert probe_duration("x.ogg") == 7523.456


def test_probe_duration_raises_on_error():
    fake_run = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="not found"
    )
    with patch("gski.audioscope_utils.subprocess.run", return_value=fake_run):
        import pytest
        with pytest.raises(RuntimeError, match="ffprobe failed"):
            probe_duration("x.ogg")
```

**Step 2: Run test (expect ImportError)**
```bash
pytest tests/test_audioscope_utils.py -v
```
Expected: FAIL — `gski.audioscope_utils` module not found.

**Step 3: Minimal implementation**

Create `gski/audioscope_utils.py`:
```python
import subprocess


def probe_duration(path: str) -> float:
    """Return audio duration in seconds via ffprobe."""
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
```

**Step 4: Run tests**
```bash
pytest tests/test_audioscope_utils.py -v
```
Expected: 2 passed.

**Step 5: Commit**
```bash
git add gski/audioscope_utils.py tests/__init__.py tests/test_audioscope_utils.py
git commit -m "audioscope: add probe_duration helper with tests"
```

---

## Task 3: Timestamp parse/format + second math

**Files:**
- Modify: `gski/audioscope_utils.py`
- Test: `tests/test_audioscope_utils.py`

**Rationale:** We'll be shifting timestamps by chunk offsets. Need robust MM:SS / H:MM:SS parsing. LLM output is inconsistent about leading zeros.

**Step 1: Add failing tests to `tests/test_audioscope_utils.py`**

```python
import pytest
from gski.audioscope_utils import parse_ts, format_ts, shift_ts


@pytest.mark.parametrize("s,expected", [
    ("00:00", 0),
    ("0:05", 5),
    ("1:30", 90),
    ("01:30", 90),
    ("59:59", 3599),
    ("1:00:00", 3600),
    ("1:23:45", 5025),
    ("01:23:45", 5025),
])
def test_parse_ts(s, expected):
    assert parse_ts(s) == expected


def test_parse_ts_invalid():
    with pytest.raises(ValueError):
        parse_ts("garbage")
    with pytest.raises(ValueError):
        parse_ts("1:2:3:4")


@pytest.mark.parametrize("sec,expected", [
    (0, "00:00"),
    (5, "00:05"),
    (90, "01:30"),
    (3599, "59:59"),
    (3600, "1:00:00"),
    (5025, "1:23:45"),
])
def test_format_ts(sec, expected):
    assert format_ts(sec) == expected


def test_shift_ts():
    assert shift_ts("00:30", 60) == "01:30"
    assert shift_ts("05:00", 3600) == "1:05:00"
```

**Step 2: Run — expect FAIL (imports)**
```bash
pytest tests/test_audioscope_utils.py -v
```

**Step 3: Implement**

Append to `gski/audioscope_utils.py`:
```python
def parse_ts(s: str) -> int:
    """Parse MM:SS or H:MM:SS into seconds."""
    parts = s.strip().split(":")
    if len(parts) == 2:
        m, sec = parts
        return int(m) * 60 + int(sec)
    if len(parts) == 3:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + int(sec)
    raise ValueError(f"invalid timestamp: {s!r}")


def format_ts(seconds: int) -> str:
    """Format seconds as MM:SS or H:MM:SS (if >= 1h)."""
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
```

**Step 4: Run tests**
```bash
pytest tests/test_audioscope_utils.py -v
```
Expected: all passing.

**Step 5: Commit**
```bash
git add gski/audioscope_utils.py tests/test_audioscope_utils.py
git commit -m "audioscope: add timestamp parse/format/shift utils"
```

---

## Task 4: Audio chunk splitter via ffmpeg

**Files:**
- Modify: `gski/audioscope_utils.py`
- Test: `tests/test_audioscope_utils.py`

**Rationale:** Given duration, compute chunk boundaries with overlap, and shell out to ffmpeg to produce chunk files.

**Chunk math invariants:**
- Chunk length: `chunk_len_sec` (default 900 = 15 min)
- Overlap: `overlap_sec` (default 30)
- Stride: `chunk_len_sec - overlap_sec` (default 870)
- Chunk N covers `[N*stride, N*stride + chunk_len_sec]` (clipped to duration)
- Number of chunks: `ceil((duration - overlap_sec) / stride)` if `duration > chunk_len_sec` else 1
- Last chunk may be shorter; never emit chunks shorter than `min_chunk_sec` (default 60) — instead merge tail into previous.

**Step 1: Add failing test for `plan_chunks`**

```python
from gski.audioscope_utils import plan_chunks, ChunkSpec


def test_plan_chunks_short_audio_one_chunk():
    chunks = plan_chunks(duration_sec=600, chunk_len_sec=900, overlap_sec=30)
    assert chunks == [ChunkSpec(index=0, start=0, end=600)]


def test_plan_chunks_exact_boundary():
    # 30-minute audio, 15-min chunks, 30s overlap:
    # stride=870; ceil((1800-30)/870)=ceil(2.03)=3 -> but 3rd chunk starts at 1740, ends at 1800 (60s left) => keep
    chunks = plan_chunks(duration_sec=1800, chunk_len_sec=900, overlap_sec=30)
    assert len(chunks) == 3
    assert chunks[0] == ChunkSpec(0, 0, 900)
    assert chunks[1] == ChunkSpec(1, 870, 1770)
    assert chunks[2] == ChunkSpec(2, 1740, 1800)


def test_plan_chunks_merges_tiny_tail():
    # duration just past one stride: tail would be 10s, merge into prev
    chunks = plan_chunks(duration_sec=910, chunk_len_sec=900, overlap_sec=30, min_chunk_sec=60)
    assert len(chunks) == 1
    assert chunks[0] == ChunkSpec(0, 0, 910)


def test_plan_chunks_2h():
    # 2h05m call matching audio-05-08
    chunks = plan_chunks(duration_sec=7523, chunk_len_sec=900, overlap_sec=30)
    assert len(chunks) == 9  # 7523/870 = 8.65 -> 9 chunks
    assert chunks[0].start == 0
    assert chunks[-1].end == 7523
    # every chunk overlaps prev by 30s:
    for prev, curr in zip(chunks, chunks[1:]):
        assert prev.end - curr.start == 30
```

**Step 2: Implement**

Append to `gski/audioscope_utils.py`:
```python
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkSpec:
    index: int
    start: int  # seconds
    end: int    # seconds (exclusive-ish; ffmpeg -to)

    @property
    def duration(self) -> int:
        return self.end - self.start


def plan_chunks(
    duration_sec: float,
    chunk_len_sec: int = 900,
    overlap_sec: int = 30,
    min_chunk_sec: int = 60,
) -> list[ChunkSpec]:
    """Compute chunk boundaries for fixed-length splitting with overlap."""
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

    # Merge tiny tail into previous chunk
    if len(chunks) >= 2 and chunks[-1].duration < min_chunk_sec:
        prev = chunks[-2]
        last = chunks[-1]
        chunks[-2] = ChunkSpec(prev.index, prev.start, last.end)
        chunks.pop()
        # re-index
        chunks = [ChunkSpec(i, c.start, c.end) for i, c in enumerate(chunks)]

    return chunks
```

**Step 3: Run tests**
```bash
pytest tests/test_audioscope_utils.py::test_plan_chunks_short_audio_one_chunk tests/test_audioscope_utils.py::test_plan_chunks_exact_boundary tests/test_audioscope_utils.py::test_plan_chunks_merges_tiny_tail tests/test_audioscope_utils.py::test_plan_chunks_2h -v
```
Expected: 4 passed.

**Step 4: Add `extract_chunk` shell-out helper**

Append to `gski/audioscope_utils.py`:
```python
def extract_chunk(src: str, dest: str, start_sec: int, end_sec: int) -> None:
    """Extract [start_sec, end_sec) of src into dest (OGG/Opus). Uses stream copy if src is already Opus."""
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
```

No unit test for this (filesystem + binary). It gets exercised in integration tests.

**Step 5: Commit**
```bash
git add gski/audioscope_utils.py tests/test_audioscope_utils.py
git commit -m "audioscope: add plan_chunks and extract_chunk helpers"
```

---

## Task 5: Validators — duration, loop, gap

**Files:**
- Create: `gski/audioscope_validators.py`
- Test: `tests/test_audioscope_validators.py`

**Rationale:** After each chunk transcription, three independent checks determine if the chunk is good or must be retried.

**Contract:** Each validator returns `ValidationResult(ok: bool, reason: str | None)`. A chunk result is a list of segments dict-shape `{"s": str, "t": "MM:SS", "x": str}` (flat schema from next task, but validators only consume this shape).

**Step 1: Failing tests**

Create `tests/test_audioscope_validators.py`:
```python
from gski.audioscope_validators import (
    check_duration, check_loop, check_gaps, ValidationResult,
)


def seg(t, speaker="A", text="hello"):
    return {"s": speaker, "t": t, "x": text}


# --- duration ---

def test_duration_ok_when_last_ts_close_to_duration():
    segments = [seg("00:00"), seg("14:30")]
    # chunk covers 0..900s, last ts at 870s -> within 60s
    r = check_duration(segments, chunk_duration_sec=900, threshold_sec=60)
    assert r.ok


def test_duration_fail_when_last_ts_too_far_from_duration():
    segments = [seg("00:00"), seg("05:00")]  # only 5min in 15-min chunk
    r = check_duration(segments, chunk_duration_sec=900, threshold_sec=60)
    assert not r.ok
    assert "truncat" in r.reason.lower() or "short" in r.reason.lower()


def test_duration_fail_on_empty():
    r = check_duration([], chunk_duration_sec=900, threshold_sec=60)
    assert not r.ok


# --- loop ---

def test_loop_detects_repeated_5gram():
    repeated = "the quick brown fox jumps over the lazy dog"
    segments = [seg("00:00", text=repeated)] * 10
    r = check_loop(segments, n=5, max_repeats=4)
    assert not r.ok
    assert "loop" in r.reason.lower() or "repeat" in r.reason.lower()


def test_loop_ok_on_normal_transcript():
    segments = [
        seg("00:00", text="hello everyone welcome to the meeting"),
        seg("00:10", text="today we will discuss the roadmap"),
        seg("00:25", text="first topic is the new feature rollout"),
    ]
    r = check_loop(segments, n=5, max_repeats=4)
    assert r.ok


# --- gaps ---

def test_gap_ok_when_segments_dense():
    segments = [seg("00:00"), seg("00:30"), seg("01:00"), seg("14:00")]
    r = check_gaps(segments, max_gap_sec=180)
    assert r.ok


def test_gap_fail_on_large_silence():
    segments = [seg("00:00"), seg("05:00"), seg("14:00")]  # 9-min gap
    r = check_gaps(segments, max_gap_sec=180)
    assert not r.ok
    assert "gap" in r.reason.lower()
```

**Step 2: Run — FAIL (module missing)**
```bash
pytest tests/test_audioscope_validators.py -v
```

**Step 3: Implement**

Create `gski/audioscope_validators.py`:
```python
import re
from dataclasses import dataclass
from collections import Counter

from gski.audioscope_utils import parse_ts


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str | None = None


def _last_ts_sec(segments) -> int | None:
    for seg in reversed(segments):
        if seg.get("t"):
            try:
                return parse_ts(seg["t"])
            except ValueError:
                continue
    return None


def check_duration(segments, chunk_duration_sec: int, threshold_sec: int = 60) -> ValidationResult:
    if not segments:
        return ValidationResult(False, "empty transcript")
    last = _last_ts_sec(segments)
    if last is None:
        return ValidationResult(False, "no parseable timestamps")
    delta = chunk_duration_sec - last
    if delta > threshold_sec:
        return ValidationResult(
            False,
            f"transcript likely truncated: last_ts={last}s, chunk={chunk_duration_sec}s (delta={delta}s)"
        )
    # last_ts being > duration + threshold means hallucinated ts
    if last - chunk_duration_sec > threshold_sec:
        return ValidationResult(
            False,
            f"last_ts {last}s exceeds chunk duration {chunk_duration_sec}s (likely loop)"
        )
    return ValidationResult(True)


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def check_loop(segments, n: int = 5, max_repeats: int = 4) -> ValidationResult:
    tokens = []
    for seg in segments:
        tokens.extend(_WORD_RE.findall((seg.get("x") or "").lower()))
    if len(tokens) < n * (max_repeats + 1):
        return ValidationResult(True)  # too short to judge

    shingles = [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
    counts = Counter(shingles)
    top_gram, top_count = counts.most_common(1)[0]
    if top_count > max_repeats:
        return ValidationResult(
            False,
            f"repetition loop detected: {n}-gram {' '.join(top_gram)!r} appears {top_count}x"
        )
    return ValidationResult(True)


def check_gaps(segments, max_gap_sec: int = 180) -> ValidationResult:
    prev_sec = None
    for seg in segments:
        if not seg.get("t"):
            continue
        try:
            cur = parse_ts(seg["t"])
        except ValueError:
            continue
        if prev_sec is not None and cur - prev_sec > max_gap_sec:
            return ValidationResult(
                False,
                f"coverage gap {cur - prev_sec}s at {seg['t']} (threshold {max_gap_sec}s)"
            )
        prev_sec = cur
    return ValidationResult(True)
```

**Step 4: Run tests**
```bash
pytest tests/test_audioscope_validators.py -v
```
Expected: all passing.

**Step 5: Commit**
```bash
git add gski/audioscope_validators.py tests/test_audioscope_validators.py
git commit -m "audioscope: add duration/loop/gap validators"
```

---

## Task 6: Merge overlapping chunks with timestamp offsets and dedup

**Files:**
- Create: `gski/audioscope_merge.py`
- Test: `tests/test_audioscope_merge.py`

**Algorithm:**
1. For each chunk N, shift all segment timestamps by `chunk.start` seconds (global coords).
2. Append segments to global list.
3. For N ≥ 1: find the overlap boundary (global time = `chunk[N].start` to `chunk[N-1].end`). Within that window compare segment texts of tail-of-N-1 vs head-of-N using `difflib.SequenceMatcher.ratio()` ≥ 0.6 — drop the head-of-N duplicate.
4. Never drop beyond the overlap window.

**Step 1: Failing tests**

Create `tests/test_audioscope_merge.py`:
```python
from gski.audioscope_merge import merge_chunks
from gski.audioscope_utils import ChunkSpec


def seg(t, x, s="A"):
    return {"s": s, "t": t, "x": x}


def test_merge_no_overlap_shifts_timestamps():
    c0 = ChunkSpec(0, 0, 900)
    c1 = ChunkSpec(1, 870, 1800)
    r0 = [seg("00:10", "alpha"), seg("14:30", "omega")]
    r1 = [seg("00:40", "beta"), seg("14:00", "gamma")]
    merged = merge_chunks([(c0, r0), (c1, r1)])
    # chunk1 starts at 870s, so "00:40" -> 910s -> "15:10"
    assert [s["x"] for s in merged] == ["alpha", "omega", "beta", "gamma"]
    assert [s["t"] for s in merged] == ["00:10", "14:30", "15:10", "29:00"]


def test_merge_drops_duplicate_in_overlap():
    c0 = ChunkSpec(0, 0, 900)
    c1 = ChunkSpec(1, 870, 1800)
    # "omega" utterance appears both at end of c0 and start of c1 (inside overlap 870-900)
    r0 = [seg("00:10", "alpha"), seg("14:35", "see you tomorrow everyone")]
    r1 = [seg("00:05", "see you tomorrow everyone"), seg("02:00", "new content")]
    merged = merge_chunks([(c0, r0), (c1, r1)])
    texts = [s["x"] for s in merged]
    assert texts.count("see you tomorrow everyone") == 1
    assert "new content" in texts


def test_merge_keeps_distinct_utterances_in_overlap():
    c0 = ChunkSpec(0, 0, 900)
    c1 = ChunkSpec(1, 870, 1800)
    r0 = [seg("14:50", "final words of chunk zero")]
    r1 = [seg("00:05", "opening words of chunk one")]  # global 875s, inside overlap but different text
    merged = merge_chunks([(c0, r0), (c1, r1)])
    assert len(merged) == 2
```

**Step 2: Run — FAIL**
```bash
pytest tests/test_audioscope_merge.py -v
```

**Step 3: Implement**

Create `gski/audioscope_merge.py`:
```python
from difflib import SequenceMatcher

from gski.audioscope_utils import ChunkSpec, parse_ts, shift_ts


DUP_SIMILARITY_THRESHOLD = 0.6


def _shift_segments(segments, offset_sec):
    out = []
    for seg in segments:
        new = dict(seg)
        if seg.get("t"):
            try:
                new["t"] = shift_ts(seg["t"], offset_sec)
            except ValueError:
                pass
        out.append(new)
    return out


def _is_duplicate(a: dict, b: dict) -> bool:
    ta = (a.get("x") or "").strip().lower()
    tb = (b.get("x") or "").strip().lower()
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    return SequenceMatcher(None, ta, tb).ratio() >= DUP_SIMILARITY_THRESHOLD


def merge_chunks(chunk_results: list[tuple[ChunkSpec, list[dict]]]) -> list[dict]:
    if not chunk_results:
        return []

    first_chunk, first_segs = chunk_results[0]
    merged = _shift_segments(first_segs, first_chunk.start)

    for prev_chunk, (chunk, segs) in zip(
        [c for c, _ in chunk_results[:-1]], chunk_results[1:]
    ):
        shifted = _shift_segments(segs, chunk.start)
        overlap_start = chunk.start
        overlap_end = prev_chunk.end

        # Segments of current chunk that fall inside the overlap window
        deduped = []
        for seg in shifted:
            try:
                ts_sec = parse_ts(seg.get("t", "00:00"))
            except ValueError:
                deduped.append(seg)
                continue
            if overlap_start <= ts_sec <= overlap_end:
                # Check against tail of merged in same window
                tail = [
                    m for m in merged
                    if m.get("t") and parse_ts(m["t"]) >= overlap_start
                ]
                if any(_is_duplicate(seg, m) for m in tail):
                    continue
            deduped.append(seg)

        merged.extend(deduped)

    return merged
```

**Step 4: Run tests**
```bash
pytest tests/test_audioscope_merge.py -v
```
Expected: 3 passed.

**Step 5: Commit**
```bash
git add gski/audioscope_merge.py tests/test_audioscope_merge.py
git commit -m "audioscope: add chunk merge with overlap dedup"
```

---

## Task 7: Single-shot Gemini call with hardened config (extract from current `run`)

**Files:**
- Modify: `gski/audioscope.py`
- Create: `gski/audioscope_gemini.py`
- Test: `tests/test_audioscope_gemini.py` (config assembly only — no real API)

**Rationale:** We want one well-tested function `transcribe_once(client, audio_path, prompt, diarize, timestamps, model, context=None) -> dict | str` used both for short-file path and per-chunk. Centralizes: flat schema, gen config hardening, Files API upload, parse or raise.

**Flat schema (new):**
```python
FLAT_DIARIZE_TS_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    description="Diarized transcript segments",
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "s": types.Schema(type=types.Type.STRING, description="Speaker (e.g. Speaker 1)"),
            "t": types.Schema(type=types.Type.STRING, description="MM:SS timestamp"),
            "x": types.Schema(type=types.Type.STRING, description="Transcribed text"),
        },
        required=["s", "t", "x"],
    ),
)
```

`summary` field is dropped — it forces an extra reasoning pass and costs tokens. If the user wants a summary, they can run `gski llm-process` on the transcript.

**Generation config for diarize:**
```python
types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=FLAT_DIARIZE_TS_SCHEMA,
    temperature=0.0,
    top_p=0.0,
    top_k=1,
    candidate_count=1,
    seed=42,
    max_output_tokens=32000,          # per-chunk is plenty for 15 min
    thinking_config=types.ThinkingConfig(thinking_budget=0),
)
```

Gracefully handle SDK not supporting some kwargs: wrap in `try/except TypeError` and drop unknown fields (log warning once). SDK version is `google-genai>=1.0` per pyproject — if `ThinkingConfig` or `thinking_budget` attr missing, omit.

**Step 1: Write tests (config construction only)**

Create `tests/test_audioscope_gemini.py`:
```python
from gski.audioscope_gemini import build_diarize_config, build_prompt_for_chunk


def test_build_diarize_config_has_flat_schema_and_hardened_params():
    cfg = build_diarize_config(timestamps=True)
    # SDK config object — inspect via .__dict__ or attributes that exist
    assert cfg.response_mime_type == "application/json"
    # schema shape
    schema = cfg.response_schema
    assert schema.type.name == "ARRAY"
    assert set(schema.items.properties.keys()) == {"s", "t", "x"}
    # hardened gen params
    assert cfg.temperature == 0.0
    assert cfg.top_p == 0.0
    assert cfg.top_k == 1
    assert cfg.candidate_count == 1
    assert cfg.seed == 42


def test_build_prompt_includes_duration_hint():
    p = build_prompt_for_chunk(
        chunk_index=2, total_chunks=5,
        chunk_start_sec=1740, chunk_duration_sec=900,
        diarize=True, timestamps=True, prev_tail=None,
    )
    assert "900" in p or "15:00" in p or "15 min" in p.lower()
    assert "NEVER REPEAT" in p.upper()


def test_build_prompt_with_prev_tail_injects_context():
    p = build_prompt_for_chunk(
        chunk_index=1, total_chunks=2,
        chunk_start_sec=870, chunk_duration_sec=900,
        diarize=True, timestamps=True,
        prev_tail=[
            {"s": "Speaker 1", "t": "14:50", "x": "last words"},
            {"s": "Speaker 2", "t": "14:55", "x": "reply"},
        ],
    )
    assert "Speaker 1" in p
    assert "last words" in p
```

**Step 2: Run — FAIL (module missing)**
```bash
pytest tests/test_audioscope_gemini.py -v
```

**Step 3: Implement**

Create `gski/audioscope_gemini.py`:
```python
import json
from google.genai import types


FLAT_DIARIZE_TS_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "s": types.Schema(type=types.Type.STRING, description="Speaker"),
            "t": types.Schema(type=types.Type.STRING, description="MM:SS timestamp"),
            "x": types.Schema(type=types.Type.STRING, description="Transcribed text"),
        },
        required=["s", "t", "x"],
    ),
)

FLAT_DIARIZE_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "s": types.Schema(type=types.Type.STRING),
            "x": types.Schema(type=types.Type.STRING),
        },
        required=["s", "x"],
    ),
)


def _thinking_config_kwargs():
    """Return dict with thinking_config if SDK supports it, else {}."""
    if not hasattr(types, "ThinkingConfig"):
        return {}
    try:
        return {"thinking_config": types.ThinkingConfig(thinking_budget=0)}
    except (TypeError, AttributeError):
        return {}


def build_diarize_config(timestamps: bool, max_output_tokens: int = 32000):
    schema = FLAT_DIARIZE_TS_SCHEMA if timestamps else FLAT_DIARIZE_SCHEMA
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.0,
        top_p=0.0,
        top_k=1,
        candidate_count=1,
        seed=42,
        max_output_tokens=max_output_tokens,
        **_thinking_config_kwargs(),
    )


ANTI_LOOP_DIRECTIVE = (
    "IMPERATIVE DIRECTIVE: NEVER REPEAT. If you detect that you are transcribing "
    "the same sequence of words in an unnatural and repetitive manner, interpret "
    "this as a signal of incomprehensible audio. Immediately break the loop, output "
    "[incomprehensible], and proceed to the next distinct segment. "
    "Do not paraphrase to fill gaps. Transcribe exactly what is said, in the original language."
)


def build_prompt_for_chunk(
    *,
    chunk_index: int,
    total_chunks: int,
    chunk_start_sec: int,
    chunk_duration_sec: int,
    diarize: bool,
    timestamps: bool,
    prev_tail: list[dict] | None = None,
) -> str:
    mins = chunk_duration_sec // 60
    secs = chunk_duration_sec % 60
    dur_str = f"{mins:02d}:{secs:02d}"

    parts = [ANTI_LOOP_DIRECTIVE]

    if total_chunks > 1:
        parts.append(
            f"This audio is chunk {chunk_index + 1} of {total_chunks} from a longer recording. "
            f"It is exactly {dur_str} long ({chunk_duration_sec} seconds). "
            f"Transcribe it completely from 00:00 to {dur_str}. "
            f"Timestamps must be RELATIVE to this chunk (start at 00:00), not to the full recording."
        )
    else:
        parts.append(
            f"This audio is exactly {dur_str} long. "
            f"Transcribe it completely from 00:00 to {dur_str}."
        )

    if diarize and timestamps:
        parts.append(
            "Generate a transcript with speaker diarization. "
            "Label each speaker (Speaker 1, Speaker 2, etc). "
            "Group consecutive speech by the same speaker into segments. "
            "Provide accurate MM:SS timestamps for each segment."
        )
    elif diarize:
        parts.append(
            "Generate a transcript with speaker diarization. "
            "Label each speaker (Speaker 1, Speaker 2, etc)."
        )
    elif timestamps:
        parts.append(
            "Generate a transcript with accurate MM:SS timestamps for each segment."
        )
    else:
        parts.append("Generate a transcript of the speech.")

    if prev_tail:
        tail_str = "\n".join(
            f"[{s.get('t', '')}] {s.get('s', 'Speaker')}: {s.get('x', '')}"
            for s in prev_tail
        )
        parts.append(
            "Previous chunk ended with these utterances. "
            "Maintain consistent speaker identities (same voice = same Speaker N label). "
            "Do NOT re-transcribe these — start after them:\n" + tail_str
        )

    return "\n\n".join(parts)
```

**Step 4: Run tests**
```bash
pytest tests/test_audioscope_gemini.py -v
```
Expected: 3 passed.

**Step 5: Commit**
```bash
git add gski/audioscope_gemini.py tests/test_audioscope_gemini.py
git commit -m "audioscope: add flat schema + hardened gen config + chunk prompt builder"
```

---

## Task 8: `transcribe_chunk` — single chunk call with retry loop

**Files:**
- Modify: `gski/audioscope_gemini.py`
- Test: `tests/test_audioscope_gemini.py`

**Contract:**
```python
transcribe_chunk(
    client, model, audio_path, config, prompt
) -> tuple[list[dict], dict]  # (segments, meta)
```
- `meta` contains `finish_reason`, `input_tokens`, `output_tokens`, `raw_text`, `attempts`.
- Raises `ChunkTranscriptionError(meta)` if JSON invalid or finish_reason=MAX_TOKENS after retries.

Retry logic **inside** transcribe_chunk is OFF for this task — we do it in the driver (Task 9). This function just does one API call + parse.

**Step 1: Failing test (mock client)**

Add to `tests/test_audioscope_gemini.py`:
```python
from unittest.mock import MagicMock
from gski.audioscope_gemini import transcribe_chunk, ChunkTranscriptionError


def test_transcribe_chunk_parses_valid_json():
    client = MagicMock()
    response = MagicMock()
    response.text = '[{"s":"Speaker 1","t":"00:05","x":"hi"}]'
    response.candidates = [MagicMock(finish_reason="STOP")]
    response.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)
    client.models.generate_content.return_value = response

    segs, meta = transcribe_chunk(
        client, model="gemini-3-flash-preview",
        audio_part=MagicMock(), config=None, prompt="test",
    )
    assert segs == [{"s": "Speaker 1", "t": "00:05", "x": "hi"}]
    assert meta["finish_reason"] == "STOP"


def test_transcribe_chunk_raises_on_invalid_json():
    import pytest
    client = MagicMock()
    response = MagicMock()
    response.text = '[{"s":"Sp'  # truncated
    response.candidates = [MagicMock(finish_reason="MAX_TOKENS")]
    response.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)
    client.models.generate_content.return_value = response

    with pytest.raises(ChunkTranscriptionError) as e:
        transcribe_chunk(
            client, model="gemini-3-flash-preview",
            audio_part=MagicMock(), config=None, prompt="test",
        )
    assert e.value.meta["finish_reason"] == "MAX_TOKENS"
    assert "[{" in e.value.meta["raw_text"]
```

**Step 2: Implement**

Append to `gski/audioscope_gemini.py`:
```python
class ChunkTranscriptionError(Exception):
    def __init__(self, message: str, meta: dict):
        super().__init__(message)
        self.meta = meta


def _response_meta(response) -> dict:
    finish = None
    try:
        finish = str(response.candidates[0].finish_reason)
    except (AttributeError, IndexError, TypeError):
        pass
    usage = getattr(response, "usage_metadata", None)
    return {
        "finish_reason": finish,
        "input_tokens": getattr(usage, "prompt_token_count", None),
        "output_tokens": getattr(usage, "candidates_token_count", None),
        "raw_text": response.text or "",
    }


def transcribe_chunk(client, *, model, audio_part, config, prompt):
    contents = [audio_part, prompt]
    response = client.models.generate_content(
        model=model, contents=contents, config=config,
    )
    meta = _response_meta(response)

    try:
        data = json.loads(meta["raw_text"])
    except (json.JSONDecodeError, TypeError) as e:
        raise ChunkTranscriptionError(f"invalid JSON: {e}", meta) from e

    if not isinstance(data, list):
        raise ChunkTranscriptionError(
            f"expected JSON array, got {type(data).__name__}", meta
        )

    return data, meta
```

**Step 3: Run tests**
```bash
pytest tests/test_audioscope_gemini.py -v
```
Expected: all 5 pass.

**Step 4: Commit**
```bash
git add gski/audioscope_gemini.py tests/test_audioscope_gemini.py
git commit -m "audioscope: add transcribe_chunk with JSON parsing and error propagation"
```

---

## Task 9: Pipeline driver — `transcribe_long`

**Files:**
- Create: `gski/audioscope_pipeline.py`
- Test: `tests/test_audioscope_pipeline.py`

**Contract:**
```python
transcribe_long(
    client, *, audio_path, model, diarize, timestamps,
    chunk_len_sec=900, overlap_sec=30,
    tmp_dir, output_dir,
    validators_enabled=True, max_retries_per_chunk=2,
) -> dict  # {"segments": [...], "chunks_meta": [...], "warnings": [...]}
```

Steps:
1. `duration = probe_duration(audio_path)`.
2. `chunks = plan_chunks(duration, chunk_len_sec, overlap_sec)`.
3. If `len(chunks) == 1`: single upload + `transcribe_chunk`, no validator retry gymnastics, return. (Keeps short-audio path simple.)
4. Otherwise: for each chunk in order, `extract_chunk` to `tmp_dir/chunk_{i:03d}.ogg`, upload via Files API (all chunks are > 15MB threshold practically; always upload for chunks), call `transcribe_chunk`, validate, retry with perturbed seed if any validator fails. Collect chunk tail (last 5 segs) to inject into next chunk's prompt.
5. After all chunks done: merge via `merge_chunks` using global offsets.
6. Save artifacts: `<output_dir>/audioscope_<ts>/` with `chunk_NNN.raw.txt`, `chunk_NNN.meta.json`, `merged.json`, `merged.txt`.

**Retry policy:**
- Attempt 1: default config
- Attempt 2: seed=43, temperature=0.0
- Attempt 3: seed=44, temperature=0.1 (last resort)
- After 3 attempts failing: record warning, keep partial segments if any, continue.

**Step 1: Failing tests (heavily mocked — no real Gemini, no real ffmpeg)**

Create `tests/test_audioscope_pipeline.py`:
```python
from unittest.mock import MagicMock, patch
from pathlib import Path

from gski.audioscope_pipeline import transcribe_long


def test_transcribe_long_single_chunk_short_audio(tmp_path):
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")

    client = MagicMock()
    response = MagicMock()
    response.text = '[{"s":"Speaker 1","t":"00:05","x":"hello"}]'
    response.candidates = [MagicMock(finish_reason="STOP")]
    response.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)
    client.models.generate_content.return_value = response
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=600):
        result = transcribe_long(
            client,
            audio_path=str(audio),
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
        )

    assert len(result["segments"]) == 1
    assert result["segments"][0]["x"] == "hello"
    assert len(result["chunks_meta"]) == 1


def test_transcribe_long_multi_chunk_success(tmp_path):
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    client = MagicMock()

    def fake_generate(model, contents, config):
        r = MagicMock()
        r.candidates = [MagicMock(finish_reason="STOP")]
        r.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)
        # chunk index inferred by call order (0,1,2,...)
        idx = client.models.generate_content.call_count - 1
        # fill all 15 minutes so duration validator passes
        r.text = (
            '[{"s":"Speaker 1","t":"00:05","x":"chunk ' + str(idx) + ' start"},'
            '{"s":"Speaker 1","t":"14:50","x":"chunk ' + str(idx) + ' end"}]'
        )
        return r
    client.models.generate_content.side_effect = fake_generate
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=1800), \
         patch("gski.audioscope_pipeline.extract_chunk") as mock_extract:
        result = transcribe_long(
            client,
            audio_path=str(audio),
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
            chunk_len_sec=900, overlap_sec=30,
        )

    assert mock_extract.call_count == 3  # 1800s / 870s stride → 3 chunks
    # segments have global timestamps
    assert result["segments"][0]["t"] == "00:05"
    # second chunk starts at 870s → its 00:05 becomes 14:35
    assert any("chunk 1 start" in s["x"] for s in result["segments"])


def test_transcribe_long_retries_failed_chunk(tmp_path):
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    client = MagicMock()

    bad = MagicMock()
    bad.text = '[{"s":"A","t":"00:00","x":"hi"}]'  # only 0s of a 900s chunk → duration fail
    bad.candidates = [MagicMock(finish_reason="STOP")]
    bad.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=5)

    good = MagicMock()
    good.text = '[{"s":"A","t":"14:50","x":"complete"}]'
    good.candidates = [MagicMock(finish_reason="STOP")]
    good.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)

    client.models.generate_content.side_effect = [bad, good]  # chunk 0 fails once, passes retry
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=900), \
         patch("gski.audioscope_pipeline.extract_chunk"):
        result = transcribe_long(
            client, audio_path=str(audio),
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
        )

    # duration=900s = single-chunk path — this test should instead force multi-chunk by reducing chunk_len
    # simpler: assert the retry happened by call count
    assert client.models.generate_content.call_count >= 1
```

Note: the third test as written is weak because 900s = single chunk. Either (a) adjust fixture to duration=1500 and chunk_len=900 (forces 2 chunks), or (b) accept it as a smoke test. Prefer (a) — update before running.

**Step 2: Implement**

Create `gski/audioscope_pipeline.py`:
```python
import json
from datetime import datetime
from pathlib import Path

from gski.audioscope_utils import (
    probe_duration, plan_chunks, extract_chunk, ChunkSpec,
)
from gski.audioscope_gemini import (
    build_diarize_config, build_prompt_for_chunk,
    transcribe_chunk, ChunkTranscriptionError,
)
from gski.audioscope_validators import (
    check_duration, check_loop, check_gaps,
)
from gski.audioscope_merge import merge_chunks


RETRY_CONFIGS = [
    {"seed": 42, "temperature": 0.0},
    {"seed": 43, "temperature": 0.0},
    {"seed": 44, "temperature": 0.1},
]

TAIL_SEGMENTS_FOR_CONTEXT = 5


def _validate_chunk(segments, chunk_duration_sec):
    checks = [
        ("duration", check_duration(segments, chunk_duration_sec)),
        ("loop", check_loop(segments)),
        ("gaps", check_gaps(segments)),
    ]
    for name, result in checks:
        if not result.ok:
            return name, result.reason
    return None, None


def _upload_and_transcribe(
    client, *, model, chunk_path, prompt, config_kwargs, diarize, timestamps,
):
    config = build_diarize_config(
        timestamps=timestamps,
        **({k: v for k, v in config_kwargs.items() if k in {"seed", "temperature"}} or {}),
    ) if diarize else None
    # If we need to override seed/temperature, re-build config with those values.
    # (Simpler approach: always rebuild via helper.)
    uploaded = client.files.upload(file=chunk_path)
    return transcribe_chunk(
        client, model=model, audio_part=uploaded, config=config, prompt=prompt,
    )


def _transcribe_single_chunk_with_retries(
    client, *, model, chunk_path, chunk, total_chunks, prev_tail,
    diarize, timestamps,
):
    attempts = []
    for attempt_idx, overrides in enumerate(RETRY_CONFIGS):
        prompt = build_prompt_for_chunk(
            chunk_index=chunk.index,
            total_chunks=total_chunks,
            chunk_start_sec=chunk.start,
            chunk_duration_sec=chunk.duration,
            diarize=diarize, timestamps=timestamps,
            prev_tail=prev_tail,
        )
        # Rebuild config with overrides
        config = None
        if diarize:
            from gski.audioscope_gemini import FLAT_DIARIZE_TS_SCHEMA, FLAT_DIARIZE_SCHEMA, _thinking_config_kwargs
            from google.genai import types
            schema = FLAT_DIARIZE_TS_SCHEMA if timestamps else FLAT_DIARIZE_SCHEMA
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=overrides["temperature"],
                top_p=0.0,
                top_k=1,
                candidate_count=1,
                seed=overrides["seed"],
                max_output_tokens=32000,
                **_thinking_config_kwargs(),
            )

        try:
            uploaded = client.files.upload(file=chunk_path)
            segments, meta = transcribe_chunk(
                client, model=model, audio_part=uploaded, config=config, prompt=prompt,
            )
        except ChunkTranscriptionError as e:
            attempts.append({"attempt": attempt_idx, "ok": False, "error": str(e), "meta": e.meta})
            continue

        bad, reason = _validate_chunk(segments, chunk.duration)
        attempts.append({
            "attempt": attempt_idx, "ok": bad is None,
            "failed_check": bad, "reason": reason, "meta": meta,
            "segment_count": len(segments),
        })
        if bad is None:
            return segments, attempts
        # else retry

    # All retries exhausted — return the best we got (last non-error attempt's segments, if any)
    for att in reversed(attempts):
        if "segment_count" in att and att["segment_count"] > 0:
            # We don't have segments cached across retries; need to re-store them
            pass
    # Simpler: on final exhaustion, re-run the last config once more and accept whatever comes back,
    # OR just return empty + warning. Choose: return empty + warning; caller decides.
    return [], attempts


def transcribe_long(
    client, *,
    audio_path: str, model: str, diarize: bool, timestamps: bool,
    tmp_dir: Path, output_dir: Path,
    chunk_len_sec: int = 900, overlap_sec: int = 30,
):
    tmp_dir = Path(tmp_dir); tmp_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / f"audioscope_{run_ts}"
    run_dir.mkdir()

    duration = probe_duration(audio_path)
    chunks = plan_chunks(duration, chunk_len_sec, overlap_sec)

    warnings = []
    chunks_meta = []
    chunk_results = []
    prev_tail = None

    for chunk in chunks:
        if len(chunks) == 1:
            chunk_path = audio_path
        else:
            chunk_path = tmp_dir / f"chunk_{chunk.index:03d}.ogg"
            extract_chunk(audio_path, str(chunk_path), chunk.start, chunk.end)

        segments, attempts = _transcribe_single_chunk_with_retries(
            client, model=model, chunk_path=str(chunk_path),
            chunk=chunk, total_chunks=len(chunks), prev_tail=prev_tail,
            diarize=diarize, timestamps=timestamps,
        )

        # Save per-chunk artifacts
        (run_dir / f"chunk_{chunk.index:03d}.meta.json").write_text(
            json.dumps({"chunk": chunk.__dict__, "attempts": attempts}, indent=2, ensure_ascii=False, default=str)
        )
        if attempts and "meta" in attempts[-1] and attempts[-1]["meta"].get("raw_text"):
            (run_dir / f"chunk_{chunk.index:03d}.raw.txt").write_text(attempts[-1]["meta"]["raw_text"])

        chunks_meta.append({"chunk": chunk.__dict__, "attempts": attempts})
        if not segments:
            warnings.append(f"chunk {chunk.index} ({chunk.start}..{chunk.end}s) produced no valid segments")
        chunk_results.append((chunk, segments))
        if segments:
            prev_tail = segments[-TAIL_SEGMENTS_FOR_CONTEXT:]

    merged = merge_chunks(chunk_results)

    (run_dir / "merged.json").write_text(
        json.dumps(merged, indent=2, ensure_ascii=False)
    )
    # merged.txt rendering deferred to caller (audioscope.py formats it)

    return {
        "segments": merged,
        "chunks_meta": chunks_meta,
        "warnings": warnings,
        "run_dir": str(run_dir),
        "duration_sec": duration,
        "num_chunks": len(chunks),
    }
```

**Step 3: Run tests**

First fix the third test (change duration to 1500 so chunk_len=900 forces 2 chunks):
```python
# in test_transcribe_long_retries_failed_chunk, use:
with patch("gski.audioscope_pipeline.probe_duration", return_value=1500), \
     patch("gski.audioscope_pipeline.extract_chunk"):
    result = transcribe_long(
        client, audio_path=str(audio),
        model="gemini-3-flash-preview",
        diarize=True, timestamps=True,
        tmp_dir=tmp_path, output_dir=tmp_path / "out",
        chunk_len_sec=900, overlap_sec=30,
    )
# 1500s → 2 chunks. Side-effect: bad for chunk 0, good for chunk 0 retry. Then chunk 1 needs calls too.
# Extend side_effect list accordingly to cover chunk 1.
client.models.generate_content.side_effect = [bad, good, good]
```

Then:
```bash
pytest tests/test_audioscope_pipeline.py -v
```
Expected: all passing.

**Step 4: Commit**
```bash
git add gski/audioscope_pipeline.py tests/test_audioscope_pipeline.py
git commit -m "audioscope: add pipeline driver with chunking, retry, validation, merge"
```

---

## Task 10: Wire pipeline into CLI `run` function

**Files:**
- Modify: `gski/audioscope.py`
- Test: `tests/test_audioscope_cli.py` (integration-ish smoke via args parser)

**Changes to `run()`:**
1. After arg parsing, compute total audio duration (if any `--audio` files). If any single file > threshold (use `chunk_len_sec + overlap_sec + 60`, default 990s ≈ 16.5 min) AND `args.diarize`, route to `transcribe_long`.
2. Short path unchanged BUT: if `args.diarize`, use new flat schema + hardened config (call `build_diarize_config`). Output format must still be compatible with current `format_diarize` → add adapter that maps `{s,t,x}` to old `{speaker,timestamp,content}` shape for `format_diarize`, or update `format_diarize` to handle both.

Decision: **Update `format_diarize` to support flat schema** (check for `s`/`t`/`x` first, fall back to old keys).

**New CLI flags:**
- `--chunk-len-sec` (default 900)
- `--overlap-sec` (default 30)
- `--no-chunking` (force single-shot even on long audio, for debugging)

**Step 1: Update `format_diarize` in `gski/audioscope.py`**

Replace:
```python
def format_diarize(data):
    lines = []
    if isinstance(data, dict) and data.get("summary"):
        lines.append(f"Summary: {data['summary']}")
        lines.append("")
    segments = data if isinstance(data, list) else data.get("segments", [])
    for seg in segments:
        speaker = seg.get("s") or seg.get("speaker") or "Unknown"
        ts = seg.get("t") or seg.get("timestamp") or ""
        text = seg.get("x") or seg.get("content") or ""
        prefix = f"[{ts}] {speaker}" if ts else speaker
        lines.append(f"{prefix}: {text}")
    return "\n".join(lines)
```

**Step 2: Add CLI flags and routing in `run`**

Modify `register()` to add flags:
```python
p.add_argument("--chunk-len-sec", type=int, default=900,
               help="chunk length in seconds for long audio (default: 900 = 15 min)")
p.add_argument("--overlap-sec", type=int, default=30,
               help="overlap between chunks in seconds (default: 30)")
p.add_argument("--no-chunking", action="store_true",
               help="force single-shot even on long audio (debug)")
```

Modify `run()` to branch on duration:
```python
def run(args):
    # ... existing validation ...

    prompt = args.prompt or default_prompt(args)
    client = genai.Client()
    model = MODELS[args.model]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Long-audio chunked path (only when diarize + timestamps requested, single audio file)
    if (
        args.diarize and args.timestamps and len(args.audio) == 1 and not args.youtube
        and not args.no_chunking
    ):
        from gski.audioscope_utils import probe_duration
        from gski.audioscope_pipeline import transcribe_long
        import tempfile

        duration = probe_duration(args.audio[0])
        threshold = args.chunk_len_sec + args.overlap_sec + 60
        if duration > threshold:
            print(f"long audio detected ({duration:.0f}s > {threshold}s threshold), chunking...",
                  file=sys.stderr)
            with tempfile.TemporaryDirectory(prefix="audioscope_chunks_") as tmp_dir:
                result = transcribe_long(
                    client,
                    audio_path=args.audio[0],
                    model=model,
                    diarize=args.diarize, timestamps=args.timestamps,
                    chunk_len_sec=args.chunk_len_sec,
                    overlap_sec=args.overlap_sec,
                    tmp_dir=tmp_dir,
                    output_dir=output_dir,
                )
            print(format_diarize(result["segments"]))
            for w in result["warnings"]:
                print(f"warning: {w}", file=sys.stderr)
            print(f"\nsaved: {result['run_dir']}", file=sys.stderr)
            return

    # Short-audio / non-diarize path: existing flow, but with new config builder when diarize
    if args.diarize:
        from gski.audioscope_gemini import build_diarize_config
        config = build_diarize_config(timestamps=args.timestamps)
    else:
        config = None

    # ... rest of existing single-shot logic unchanged ...
```

**Step 3: Add CLI smoke test**

Create `tests/test_audioscope_cli.py`:
```python
import argparse
from gski.audioscope import register


def test_cli_parser_accepts_new_flags():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    register(sub)
    args = parser.parse_args([
        "audioscope", "--audio", "x.ogg",
        "--diarize", "--timestamps",
        "--chunk-len-sec", "600", "--overlap-sec", "20",
        "--no-chunking",
    ])
    assert args.chunk_len_sec == 600
    assert args.overlap_sec == 20
    assert args.no_chunking is True
```

**Step 4: Run all tests**
```bash
pytest tests/ -v
```
Expected: all green.

**Step 5: Commit**
```bash
git add gski/audioscope.py tests/test_audioscope_cli.py
git commit -m "audioscope: route long audio through chunked pipeline; expose chunking flags"
```

---

## Task 11: Integration smoke on real audio (manual, documented)

**Files:**
- Create: `docs/manual-smoke.md` (doc-only; captures run commands + expected artifacts)

Wait — constraint says no docs files. Instead do this via PR description / log attached in commit message. But we DO need repeatable smoke commands. Compromise: keep them in plan doc (this file), executed manually, results captured in commit message + PR body.

**Step 1: Run on 2h file (audio-05-08.ogg)**
```bash
cd /Users/iz/work/gski/.worktrees/audioscope-long-audio
gski audioscope \
  --audio /Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-08.ogg \
  --diarize --timestamps --model flash \
  --output-dir /tmp/audioscope-smoke-05-08 \
  2>&1 | tee /tmp/smoke-05-08.log
```

Expected:
- Stderr shows `long audio detected (7523s > 990s threshold), chunking...`
- 9 chunks processed
- Final transcript prints to stdout; `last timestamp` close to `2:05:2x`
- `/tmp/audioscope-smoke-05-08/audioscope_*/merged.json` exists
- Count segments: `jq 'length' /tmp/audioscope-smoke-05-08/audioscope_*/merged.json` — expect ~300–800 for 2h.

**Step 2: Verify no gaps / loops**
```bash
python3 - <<'PY'
import json, sys, glob
p = glob.glob("/tmp/audioscope-smoke-05-08/audioscope_*/merged.json")[-1]
segs = json.load(open(p))
print(f"total: {len(segs)} segments; last ts: {segs[-1]['t']}")
# crude loop detector: any 5-gram repeated >3x?
from collections import Counter
import re
tokens = [w for s in segs for w in re.findall(r'\w+', s['x'].lower())]
shingles = [tuple(tokens[i:i+5]) for i in range(len(tokens)-4)]
top = Counter(shingles).most_common(3)
print("top repeated 5-grams:", top)
PY
```
Expected: last ts near `2:05:xx`; no shingle repeated >10x.

**Step 3: Run on 2.5h file (audio-05-07.ogg)** — the file that previously looped
```bash
gski audioscope \
  --audio /Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-07.ogg \
  --diarize --timestamps --model flash \
  --output-dir /tmp/audioscope-smoke-05-07 \
  2>&1 | tee /tmp/smoke-05-07.log
```

Expected: no 14× loop; last ts close to actual duration.

**Step 4: Capture smoke results in a commit**
```bash
git commit --allow-empty -m "smoke: 2h audio-05-08 → 9 chunks, N segments, last_ts=2:05:xx, no loop"
```

Smoke results attach to PR body manually.

---

## Task 12: Update skill documentation (`SKILL.md`)

**Files:**
- Modify: `gski/skills/audioscope/SKILL.md` (if bundled) OR `/Users/iz/.config/opencode/skills/audioscope/SKILL.md`

Check which one `gski` ships. Update:
- Add `--chunk-len-sec`, `--overlap-sec`, `--no-chunking` flags to the options table
- Add brief note: "Files longer than ~16 min with `--diarize --timestamps` are automatically chunked, transcribed sequentially with speaker-identity continuity, and merged."
- Bump "Notes" section to mention per-chunk retry on validation failure.

This is the ONE documentation exception (existing file, user-facing skill spec). Keep additions minimal and factual; don't write a marketing blurb.

**Step 1: Edit SKILL.md** — append to Options table and Notes. No new sections.

**Step 2: Commit**
```bash
git add gski/skills/audioscope/SKILL.md
git commit -m "audioscope: document chunking flags in SKILL.md"
```

---

## Task 13: Open PR

**Step 1: Push branch**
```bash
cd /Users/iz/work/gski/.worktrees/audioscope-long-audio
git push -u origin feat/audioscope-long-audio
```

**Step 2: Create PR**
```bash
gh pr create --title "audioscope: chunked pipeline for long audio (diarize+timestamps)" --body "$(cat <<'EOF'
## Summary
- Introduces automatic chunked transcription path for long audio (>~16 min) when `--diarize --timestamps` is used, addressing three observed failure modes on 1-3h Google Meet recordings: silent middle-skip, repetition loops, and `MAX_TOKENS` JSON truncation.
- Adds flat JSON schema (`{s,t,x}`), hardened generation config (temperature=0, seed=42, thinking_budget=0), chunk-level retries with validators (duration/loop/gap), and overlap-aware segment merging.
- Backed by deep-research report [notes/projects/google-meet-transcribe/long-audio-gemini-sota-research](notes/projects/google-meet-transcribe/long-audio-gemini-sota-research).

## What's in / What's out

In this PR:
- ffmpeg-based 15-min chunks with 30s overlap (configurable).
- Sequential processing with speaker-context injection across chunks.
- Flat JSON schema; summary field dropped.
- Duration / 5-gram-loop / coverage-gap validators with seed-perturbation retries.
- Short-audio single-shot path preserved (now uses flat schema too).

Out of scope (tracked as follow-ups):
- pyannote-based hybrid diarization.
- Parallel chunk processing.
- LLM-as-judge transcript audit.
- Deepgram / ElevenLabs fallback on persistent failure.

## Smoke test results
(Attach smoke logs + segment counts for audio-05-07.ogg and audio-05-08.ogg here.)

## Migration notes for consumers
- Output JSON for `--diarize` now returns a flat array `[{s,t,x}, ...]` instead of `{summary, segments: [...]}`. `format_diarize` handles both shapes but downstream JSON consumers must update.
EOF
)"
```

**Step 3: Verify PR URL prints** and paste into PR tracker / daily note.

---

# PART 2 (added 2026-05-08, post-smoke): Aggressive loop & gap handling

**Context:** The initial smoke on `audio-05-08.ogg` (2h05m) passed the happy-path criteria (9 chunks, `last_ts=2:05:15`, no cross-segment loops in merged output), but deeper inspection of `merged.json` revealed two classes of remaining problems that the Task 7-12 pipeline handles poorly:

1. **Silent-middle-skip inside a chunk** (the "gaps" failure mode from deep-research). Chunk 2 produced a 186s gap at ~38:53–41:59 global; chunk 6 produced a 346s gap at ~1:33:43–1:39:29 global. All three retries produced the same gap (±1–2s). `check_gaps` correctly flagged it, pipeline retried 3× with seed/temperature perturbation, got identical output, then silently kept the longest attempt as `best_segments`. The merged transcript contains a ~5-minute hole with **no indication** that content is missing — the reader sees `[1:33:43] ...звонки начать считать` jump straight to `[1:39:29] Ну, блин...`.

2. **Whitespace/token loops that break JSON parsing.** Chunk 6 attempt 2 in the v2 smoke produced 68KB of raw output where the model MAX_TOKENS-ed on a whitespace/indent token (not a word loop — `audioscope_salvage` can't see it because JSON parsing fails first). The chunk was saved by attempts 0+1 returning word-clean output, but if all 3 attempts whitespace-loop, the entire chunk is lost with just a `ChunkTranscriptionError("invalid JSON")` logged.

3. **Deterministic seed ineffectiveness.** Current retry strategy changes only `{seed: 42→43→44, temp: 0.0→0.0→0.1}`. Empirically Gemini produces near-identical output across seeds 42/43/44 when the underlying failure is audio-content-driven (silence region, specific phonetic trigger). Three retries waste API calls without meaningfully exploring alternatives.

**What Part 2 fixes:**

- **Task 14** adds diverse retry strategies that actually change model behaviour (audio re-extraction with offset, prompt variation, shorter chunk sub-split).
- **Task 15** adds whitespace/non-JSON loop detection before JSON parsing so salvage can trim the raw_text itself.
- **Task 16** adds explicit `[…gap: Nm Ns untranscribed…]` and `[…chunk lost…]` placeholders in merged output when coverage is incomplete, so data loss is always visible to the reader.
- **Task 17** integration smoke on the same two files, with pass criteria "no unmarked gaps >180s AND no silent chunk-drops in merged.json".

**Non-goals for Part 2:**
- Not introducing pyannote, Deepgram, or any new external dep.
- Not changing the 15min/30s chunk sizes or the flat `{s,t,x}` schema.
- Not adding `--parallel` or streaming output.

---

## Task 14: Diverse retry strategies (`RETRY_CONFIGS` overhaul)

**Files:**
- Modify: `gski/audioscope_pipeline.py` (expand `RETRY_CONFIGS`, add retry-strategy dispatcher)
- Modify: `gski/audioscope_utils.py` (add `extract_chunk_with_offset` helper)
- Modify: `gski/audioscope_gemini.py` (add `build_prompt_for_chunk_retry` variant)
- Add: `tests/test_audioscope_pipeline.py` (3 new tests for each retry strategy)

**Current state:**
```python
RETRY_CONFIGS = [
    {"seed": 42, "temperature": 0.0},
    {"seed": 43, "temperature": 0.0},
    {"seed": 44, "temperature": 0.1},
]
```
All three re-submit the same audio bytes with the same prompt. Observed: chunks 2 and 6 produce byte-identical gaps across all three.

**New strategy (attempt-indexed):**

```python
RETRY_STRATEGIES = [
    # Attempt 0: default hardened config
    {"kind": "default", "seed": 42, "temperature": 0.0},
    # Attempt 1: audio perturbation — re-extract with +2s offset on start
    # (shifts internal model state for the same content, more effective
    # than seed change against content-driven skips/loops)
    {"kind": "audio_offset", "seed": 42, "temperature": 0.0, "offset_sec": 2},
    # Attempt 2: prompt variation — add explicit anti-loop instruction and
    # higher temperature. Prompt suffix appended by build_prompt_for_chunk_retry.
    {"kind": "prompt_variant", "seed": 99, "temperature": 0.2,
     "prompt_suffix": "CRITICAL: if you cannot transcribe a portion of the audio (silence, noise, unclear speech), output a single segment with x=\"[unclear]\" and continue. DO NOT repeat any word or phrase more than 3 times in a single segment. DO NOT skip audio — every minute must have at least one segment."},
]
```

**Step 1: Write failing test for `extract_chunk_with_offset`**
```python
# tests/test_audioscope_utils.py
def test_extract_chunk_with_offset_shifts_start(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        class R: returncode = 0; stderr = b""
        return R()
    monkeypatch.setattr("subprocess.run", fake_run)
    from gski.audioscope_utils import extract_chunk_with_offset
    extract_chunk_with_offset("in.ogg", str(tmp_path/"out.ogg"), start=1000, end=1900, offset_sec=2)
    # ffmpeg -ss should be 1000+2=1002, duration should be 900-2=898 (keep end fixed)
    assert "1002" in " ".join(calls[0])
    assert "898" in " ".join(calls[0])
```
Run: expect ImportError.

**Step 2: Implement `extract_chunk_with_offset`** in `gski/audioscope_utils.py`:
```python
def extract_chunk_with_offset(src, dst, *, start, end, offset_sec):
    """Extract chunk [start+offset .. end] — shifts only start, preserves end.
    Used for retry when the model missed content at the beginning of a chunk."""
    actual_start = start + offset_sec
    actual_dur = end - actual_start
    if actual_dur < 60:
        # offset too large, fall back to regular extraction
        return extract_chunk(src, dst, start, end)
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ss", str(actual_start),
         "-t", str(actual_dur), "-c", "copy", dst],
        check=True, capture_output=True,
    )
```
Run test: expect green.

**Step 3: Write failing test for `build_prompt_for_chunk_retry`**
```python
# tests/test_audioscope_gemini.py
def test_prompt_retry_variant_appends_antiloop_instruction():
    from gski.audioscope_gemini import build_prompt_for_chunk
    base = build_prompt_for_chunk(chunk_index=0, total_chunks=2,
                                  chunk_start_sec=0, chunk_duration_sec=900,
                                  diarize=True, timestamps=True, prev_tail=None,
                                  extra_instruction="CRITICAL: anti-loop directive here")
    assert "CRITICAL: anti-loop directive here" in base
    assert "DO NOT repeat" in base or "anti-loop" in base
```
Run: expect fail (kwarg unknown).

**Step 4: Extend `build_prompt_for_chunk`** to accept `extra_instruction: str | None = None` and append it to the prompt tail. Run test: green.

**Step 5: Write failing pipeline integration test**
```python
def test_retry_uses_audio_offset_on_second_attempt(tmp_path):
    """Attempt 1 must call extract_chunk_with_offset (not extract_chunk)."""
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    client = MagicMock()

    # First attempt: gap failure. Second attempt: success.
    bad = MagicMock()
    bad.text = '[{"s":"A","t":"00:00","x":"start"}]'  # short → gaps fail
    bad.candidates = [MagicMock(finish_reason="STOP")]
    bad.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=5)
    good = MagicMock()
    good.text = ('[' + ','.join(f'{{"s":"A","t":"{m:02d}:00","x":"minute {m}"}}' for m in range(15)) + ']')
    good.candidates = [MagicMock(finish_reason="STOP")]
    good.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
    client.models.generate_content.side_effect = [bad, good]
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=900), \
         patch("gski.audioscope_pipeline.extract_chunk") as mock_ex, \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset") as mock_ex_off:
        transcribe_long(client, audio_path=str(audio),
                        model="gemini-3-flash-preview",
                        diarize=True, timestamps=True,
                        tmp_dir=tmp_path, output_dir=tmp_path / "out")

    # Attempt 0: regular extract. Attempt 1: offset extract.
    assert mock_ex.call_count >= 1
    assert mock_ex_off.call_count == 1
    _args, kwargs = mock_ex_off.call_args
    assert kwargs.get("offset_sec") == 2 or 2 in _args
```
Run: expect fail (`extract_chunk_with_offset` not imported in pipeline).

**Step 6: Refactor `_transcribe_single_chunk_with_retries`** to dispatch on `strategy["kind"]`:

```python
RETRY_STRATEGIES = [ ... as above ... ]

def _apply_strategy(strategy, *, chunk, audio_path, tmp_dir, chunk_path):
    """Prepare the audio file and prompt-extra for a given retry strategy.
    Returns (chunk_path_to_upload, prompt_extra_or_None)."""
    kind = strategy["kind"]
    if kind == "default":
        return chunk_path, None
    if kind == "audio_offset":
        off_path = str(tmp_dir / f"chunk_{chunk.index:03d}.off.ogg")
        extract_chunk_with_offset(audio_path, off_path,
                                  start=chunk.start, end=chunk.end,
                                  offset_sec=strategy["offset_sec"])
        return off_path, None
    if kind == "prompt_variant":
        return chunk_path, strategy["prompt_suffix"]
    raise ValueError(f"unknown retry strategy: {kind}")

# In the retry loop:
for attempt_idx, strategy in enumerate(RETRY_STRATEGIES):
    upload_path, prompt_extra = _apply_strategy(
        strategy, chunk=chunk, audio_path=audio_path,
        tmp_dir=tmp_dir, chunk_path=chunk_path,
    )
    prompt = build_prompt_for_chunk(
        ...,
        extra_instruction=prompt_extra,
    )
    config = build_diarize_config(
        timestamps=timestamps,
        seed=strategy["seed"],
        temperature=strategy["temperature"],
    )
    uploaded = client.files.upload(file=upload_path)
    ...
```

Note: `_transcribe_single_chunk_with_retries` must now receive `audio_path` and `tmp_dir` as parameters — update callers in `transcribe_long`.

**Step 7: Update existing retry tests** (`test_transcribe_long_retries_failed_chunk`, `test_transcribe_long_rejects_looped_segments_as_fallback`) to account for the new strategies. Most should keep working because they mock `client.models.generate_content` directly.

**Step 8: Run full suite** — expect all green (48 previous + 3 new = 51).

**Step 9: Commit**
```bash
git add gski/audioscope_pipeline.py gski/audioscope_utils.py gski/audioscope_gemini.py \
        tests/test_audioscope_pipeline.py tests/test_audioscope_utils.py tests/test_audioscope_gemini.py
git commit -m "audioscope: diverse retry strategies — audio offset + prompt variant"
```

---

## Task 15: Whitespace/non-JSON loop detection before parse

**Files:**
- Modify: `gski/audioscope_gemini.py` (`transcribe_chunk`)
- Modify: `gski/audioscope_salvage.py` (new function `salvage_raw_text`)
- Add: `tests/test_audioscope_salvage.py` (3 new tests)

**Root cause:** When Gemini MAX_TOKENS-es on whitespace (or any single character), it emits e.g. `"...text",                                                                  ` (thousands of spaces) before hitting the token limit. The resulting string is invalid JSON. `transcribe_chunk` catches the `JSONDecodeError` and raises `ChunkTranscriptionError`, but the salvageable prefix (the first N valid segments before the whitespace storm) is thrown away.

**Fix:** Before json.loads, scan `raw_text` for massive whitespace or single-character runs. If detected, truncate at the last complete segment boundary (find the last `}`, then the last balanced `]` or cut after the matching comma, append `]` to close array).

**Step 1: Write failing test for `salvage_raw_text`**
```python
def test_salvage_raw_text_closes_whitespace_truncated_json():
    from gski.audioscope_salvage import salvage_raw_text
    # Simulate MAX_TOKENS on whitespace: valid prefix + whitespace storm.
    valid = '[{"s":"A","t":"00:00","x":"hello"},{"s":"B","t":"00:05","x":"world"}'
    # whitespace after the last segment's closing brace, before the array-closing ]
    broken = valid + "                                                              " * 100
    cleaned, was_salvaged = salvage_raw_text(broken)
    assert was_salvaged is True
    import json as J
    segs = J.loads(cleaned)  # must parse
    assert len(segs) == 2
    assert segs[-1]["x"] == "world"

def test_salvage_raw_text_passthrough_on_valid_json():
    valid = '[{"s":"A","t":"00:00","x":"hi"}]'
    cleaned, was = salvage_raw_text(valid)
    assert was is False
    assert cleaned == valid

def test_salvage_raw_text_detects_character_loop_inside_segment():
    # MAX_TOKENS on a single char inside x field before the closing quote.
    broken = '[{"s":"A","t":"00:00","x":"hello"},{"s":"B","t":"00:05","x":"aaaa' + 'a' * 5000
    cleaned, was = salvage_raw_text(broken)
    assert was is True
    import json as J
    segs = J.loads(cleaned)
    assert len(segs) == 1  # only the first complete segment survives
    assert segs[0]["x"] == "hello"
```
Run: expect ImportError.

**Step 2: Implement `salvage_raw_text`** in `gski/audioscope_salvage.py`:

```python
_WHITESPACE_RUN = re.compile(r"[\s]{50,}")  # 50+ whitespace chars in a row
_CHAR_RUN = re.compile(r"(.)\1{200,}")       # any char repeated 200+ times

def salvage_raw_text(raw: str) -> tuple[str, bool]:
    """Detect token-level loops in raw JSON output and truncate to the last
    complete segment. Returns (repaired_json_string, was_salvaged)."""
    # Try direct parse first.
    try:
        json.loads(raw)
        return raw, False
    except json.JSONDecodeError:
        pass

    # Look for whitespace storm or char loop signature.
    if not (_WHITESPACE_RUN.search(raw) or _CHAR_RUN.search(raw)):
        return raw, False  # JSON broken for a different reason; don't touch it

    # Find the last "}," — marks end of a complete segment object.
    # Walk back from a safe offset to avoid scanning inside the loop tail.
    cut_point = None
    depth = 0
    last_complete = -1
    in_string = False
    escape = False
    for i, ch in enumerate(raw):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 1:  # just closed one segment inside the outer array
                last_complete = i
    if last_complete < 0:
        return raw, False  # no complete segment found
    return raw[:last_complete + 1] + "]", True
```

Run tests: expect green (may need iteration on the depth tracking).

**Step 3: Wire into `transcribe_chunk`** — call `salvage_raw_text` before `json.loads`:

```python
def transcribe_chunk(client, *, model, audio_part, config, prompt):
    response = client.models.generate_content(...)
    raw_text = response.text or ""
    ...
    repaired, raw_salvaged = salvage_raw_text(raw_text)
    try:
        segments = json.loads(repaired)
    except json.JSONDecodeError as e:
        raise ChunkTranscriptionError(f"invalid JSON: {e}", meta={"raw_text": raw_text, "raw_salvaged": raw_salvaged})
    # Record raw_salvaged in meta so pipeline can log it.
    return segments, {..., "raw_salvaged": raw_salvaged}
```

**Step 4: Run full suite** — expect green.

**Step 5: Commit**
```bash
git add gski/audioscope_salvage.py gski/audioscope_gemini.py tests/test_audioscope_salvage.py
git commit -m "audioscope: salvage whitespace/char-loop truncated JSON before parse"
```

---

## Task 16: Explicit gap & lost-chunk placeholders in merge

**Files:**
- Modify: `gski/audioscope_merge.py` (inject gap segments)
- Modify: `gski/audioscope_pipeline.py` (inject lost-chunk placeholder)
- Add: tests in `tests/test_audioscope_merge.py` and `tests/test_audioscope_pipeline.py`

**Requirement:** Any coverage hole in the final merged transcript must be **visible** to a human reader. No silent data loss.

Two cases:
- **In-chunk gap** (retries accepted a chunk with `failed=gaps`): model skipped N seconds inside the chunk. Detect during merge by timestamp-diff >180s between consecutive segments within the same chunk (or across merge boundary after dedup). Inject `{"s": "__system__", "t": "<gap_start_ts>", "x": "[…gap: Nm Ns untranscribed…]"}`.
- **Lost chunk** (`segments=[]` after all retries): entire 15-min block absent. Inject `{"s": "__system__", "t": "<chunk_start_ts>", "x": "[…chunk lost: {chunk.start}s–{chunk.end}s, all retries failed…]"}`.

**Step 1: Write failing tests for merge gap insertion**
```python
# tests/test_audioscope_merge.py
def test_merge_inserts_gap_placeholder_when_adjacent_segs_have_big_time_diff():
    from gski.audioscope_merge import merge_chunks
    from gski.audioscope_utils import ChunkSpec
    c0 = ChunkSpec(index=0, start=0, end=900, duration=900)
    segs0 = [
        {"s":"A","t":"00:00","x":"hello"},
        {"s":"A","t":"01:00","x":"first minute"},
        # gap from 01:00 to 08:00 = 420s >180s threshold
        {"s":"A","t":"08:00","x":"jump ahead"},
    ]
    merged = merge_chunks([(c0, segs0)])
    # between 01:00 and 08:00 there should be a __system__ placeholder
    texts = [s["x"] for s in merged]
    assert any("gap" in t.lower() and "untranscribed" in t.lower() for t in texts)
    # placeholder timestamp inside the gap
    for s in merged:
        if "gap" in s["x"].lower():
            assert s["s"] == "__system__"
            # format: ..:.. → somewhere between 01:00 and 08:00
            break

def test_merge_no_placeholder_for_small_gap():
    from gski.audioscope_merge import merge_chunks
    from gski.audioscope_utils import ChunkSpec
    c0 = ChunkSpec(index=0, start=0, end=900, duration=900)
    segs0 = [{"s":"A","t":"00:00","x":"a"}, {"s":"A","t":"01:30","x":"b"}]  # 90s gap, OK
    merged = merge_chunks([(c0, segs0)])
    assert all("gap" not in s["x"].lower() for s in merged)
```
Run: expect fail.

**Step 2: Implement in `merge_chunks`** — after offset shift, walk through the final sequence, detect `parse_ts(cur) - parse_ts(prev) > 180` (config constant), insert `{"s":"__system__","t":"<midpoint_ts>","x":f"[…gap: {dur//60}m {dur%60}s untranscribed…]"}` between them.

Run test: green.

**Step 3: Write failing test for lost-chunk placeholder in pipeline**
```python
def test_transcribe_long_inserts_lost_chunk_placeholder(tmp_path):
    """If a chunk returns no segments after all retries, merged output must
    contain a __system__ placeholder marking the lost time range."""
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    client = MagicMock()

    # Chunk 0: good. Chunk 1: all retries raise JSON error → empty segments.
    good = MagicMock()
    good.text = ('[' + ','.join(f'{{"s":"A","t":"{m:02d}:00","x":"m{m}"}}' for m in range(15)) + ']')
    good.candidates = [MagicMock(finish_reason="STOP")]
    good.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
    bad = MagicMock()
    bad.text = 'total garbage not json'
    bad.candidates = [MagicMock(finish_reason="MAX_TOKENS")]
    bad.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=32000)
    # duration=1770 → 2 chunks. Chunk 0: good. Chunk 1: bad × 3 retries.
    client.models.generate_content.side_effect = [good, bad, bad, bad]
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=1770), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset"):
        result = transcribe_long(client, audio_path=str(audio),
                                 model="gemini-3-flash-preview",
                                 diarize=True, timestamps=True,
                                 tmp_dir=tmp_path, output_dir=tmp_path / "out")

    # merged.json must contain the __system__ lost-chunk marker
    texts = [s["x"] for s in result["segments"]]
    assert any("chunk lost" in t.lower() for t in texts)
    # system segment must have __system__ speaker
    for s in result["segments"]:
        if "chunk lost" in s["x"].lower():
            assert s["s"] == "__system__"
            break
```
Run: expect fail.

**Step 4: Implement** in `transcribe_long` — after `_transcribe_single_chunk_with_retries` returns empty segments, append a synthetic single-segment list:
```python
if not segments:
    segments = [{
        "s": "__system__",
        "t": _sec_to_ts(chunk.start),
        "x": f"[…chunk lost: {chunk.start}s–{chunk.end}s, all retries failed…]",
    }]
    warnings.append(f"chunk {chunk.index}: inserted lost-chunk placeholder")
```
(use existing `_sec_to_ts` or parse_ts inverse; add if missing).

Run test: green.

**Step 5: Update `format_diarize` in `audioscope.py`** to render `__system__` speaker differently (e.g. italicized or with `[SYSTEM]` prefix) so it stands out in human-readable output. Test via existing CLI parser test or add one.

**Step 6: Run full suite** — expect all green (51 + 4 new = 55 tests).

**Step 7: Commit**
```bash
git add gski/audioscope_merge.py gski/audioscope_pipeline.py gski/audioscope.py \
        tests/test_audioscope_merge.py tests/test_audioscope_pipeline.py
git commit -m "audioscope: insert __system__ gap/lost-chunk placeholders in merged output"
```

---

## Task 17: Re-smoke on audio-05-08 and audio-05-07

**Files:** none (manual execution + results in PR body)

**Step 1: Clean previous runs and re-run 2h file**
```bash
rm -rf /tmp/audioscope-smoke-05-08-v3
gski audioscope \
  --audio /Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-08.ogg \
  --diarize --timestamps --model flash \
  --output-dir /tmp/audioscope-smoke-05-08-v3 \
  2>&1 | tee /tmp/smoke-05-08-v3.log
```

**Step 2: Verify pass criteria**
```bash
python3 - <<'PY'
import json, re, glob
from collections import Counter
from gski.audioscope_utils import parse_ts

p = glob.glob("/tmp/audioscope-smoke-05-08-v3/audioscope_*/merged.json")[-1]
segs = json.load(open(p))

# 1. Last ts reaches near end of audio (expect ~2:05:2x)
last = segs[-1]["t"]
print(f"last ts: {last}")
assert parse_ts(last) > 2*3600 + 4*60, f"last_ts too early: {last}"

# 2. No cross-segment 5-gram repeated >10x
tokens = [w for s in segs for w in re.findall(r'\w+', s['x'].lower()) if s['s'] != '__system__']
shingles = [tuple(tokens[i:i+5]) for i in range(len(tokens)-4)]
top_sh, top_c = Counter(shingles).most_common(1)[0]
print(f"top 5-gram: {top_c}x {top_sh}")
assert top_c <= 10, f"loop detected: {top_sh} x{top_c}"

# 3. No intra-segment single-token >50 repeats
for i, s in enumerate(segs):
    if s['s'] == '__system__':
        continue
    toks = re.findall(r'\w+', s['x'].lower())
    if toks:
        t, c = Counter(toks).most_common(1)[0]
        assert c < 50, f"intra-loop seg {i}: '{t}' x{c}"

# 4. Every gap >180s must have a __system__ placeholder
real_segs = segs
prev_sec = None
for i, s in enumerate(real_segs):
    try: cur = parse_ts(s['t'])
    except: continue
    if prev_sec is not None and cur - prev_sec > 180:
        # previous or next segment should be __system__ with "gap" marker
        context = real_segs[max(0,i-2):min(len(real_segs),i+2)]
        assert any('__system__' in x['s'] or 'gap' in x['x'].lower() or 'chunk lost' in x['x'].lower()
                   for x in context), \
               f"unmarked gap {cur-prev_sec}s at seg {i} @ {s['t']}"
    prev_sec = cur

print("ALL PASS CRITERIA MET")
PY
```

**Step 3: Same for 2.5h file** (`audio-05-07.ogg`). Expect: last_ts close to 2:19:xx, no unmarked gaps.

**Step 4: Smoke results into PR body** — replace the placeholder `## Smoke test results` section in the PR with actual numbers:
- file / duration / chunks / last_ts / segments / gap-markers-count / lost-chunk-markers-count / retries-used-by-strategy

**Step 5: Commit empty marker if desired**
```bash
git commit --allow-empty -m "smoke v3: part-2 fixes verified on audio-05-08 and audio-05-07"
```

---

## Part 2 completion criteria

- [ ] 55+ tests green (48 current + ~7 new)
- [ ] Smoke v3 on both 2h and 2.5h files passes all four assertions in Task 17 Step 2
- [ ] `merged.json` for audio-05-08.ogg contains zero unmarked gaps >180s
- [ ] `merged.json` for audio-05-08.ogg chunk 6 region (1:27:00–1:42:00) is either fully covered OR contains visible `__system__` gap/lost markers for missing portions
- [ ] PR description updated with Part 2 changes summary and smoke v3 results

---

## TODO (explicitly not Part 2 either)

- pyannote 3.1 global-first hybrid diarization (`--diarize-engine pyannote`)
- Parallel chunk processing (`--parallel N`)
- LLM-as-judge validator via Flash-Lite
- Deepgram Nova-3 / ElevenLabs Scribe fallback on persistent failure
- Streaming output (`generate_content_stream`) — research says no material benefit, leave as optional UX improvement
- Sub-chunk re-submission for stubborn gaps (if a single chunk has repeated gaps across all 3 strategies, split it into 2×450s halves and retry) — evaluate in Part 3 only if Part 2 isn't sufficient

---

## Original TODO (kept for reference)

- pyannote 3.1 global-first hybrid diarization (`--diarize-engine pyannote`)
- Parallel chunk processing (`--parallel N`)
- LLM-as-judge validator via Flash-Lite
- Deepgram Nova-3 / ElevenLabs Scribe fallback on triple-retry failure
- Streaming output (`generate_content_stream`) — research says no material benefit, leave as optional UX improvement
