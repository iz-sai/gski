# Audioscope Part 3 — Salvage Failing Chunks (Pro Fallback + Sub-Chunking)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When a chunk fails all flash-model retries (validation_failures or outright loss), automatically salvage it by (1) retrying the same 15-min chunk on `gemini-3-pro-preview`, then if still failing (2) splitting into 3-minute sub-chunks and transcribing each on flash. Drive total transcript coverage toward 100%, at the cost of extra API calls, for users who have already decided cost is irrelevant.

**Architecture:** A post-pass runs after the initial chunking loop in `transcribe_long`. It identifies "unhealthy" chunks (zero segments, or `accepted with validation failures`). For each, it applies a salvage ladder: `pro_retry` → `sub_chunk_flash` → `sub_chunk_pro`. Ladder depth configurable via CLI flags. Each salvage step reuses the existing `_transcribe_chunk_with_retries` retry loop but with a different model and/or chunk-len. Results replace the original chunk's segments in `chunk_results`, then `merge_chunks` re-runs so gaps disappear. Per-chunk salvage metadata is appended to existing `chunk_NNN.meta.json`.

**Tech Stack:** Python 3.14, pytest, existing `gski.audioscope_pipeline`, `gski.audioscope_gemini`, `gski.audioscope_utils`, `gski.audioscope_validators`. No new dependencies.

---

## Context the executing agent needs

### Current state (after Part 2 + unified output + coverage summary)

- `transcribe_long()` in `gski/audioscope_pipeline.py:215` iterates chunks, calls `_transcribe_chunk_with_retries()` (line ~100), collects `(chunk, segments)` tuples, calls `merge_chunks()`, writes `merged.json`, returns dict with `segments`, `warnings`, `coverage`, `chunks_meta`.
- A chunk that produced no valid segments → placeholder `{"s":"__system__", "x":"[…chunk lost: Ns–Ms, all retries failed…]"}` inserted in its slot (line ~280).
- A chunk with `accepted with validation failures` still returns partial segments but may leave an internal gap that `_insert_gap_placeholders` in `gski/audioscope_merge.py:69` later fills with `[…gap: Xm Ys untranscribed…]`.
- `summarize_coverage(merged)` (in `audioscope_pipeline.py`) counts these; if any present, a `coverage: …` warning is appended.
- Model aliases: `gski/audioscope.py:11–14`, `MODELS = {"flash": "gemini-3-flash-preview", "pro": "gemini-3-pro-preview"}`.
- `_transcribe_chunk_with_retries()` takes `model` (full ID, not alias) as a parameter — pass `MODELS["pro"]` directly.
- Pro is known to handle 15-min Russian audio without looping (per tests in `/Users/iz/work/tasks/google-meet-transcribe/tests/t1-pro-default`).

### Why sub-chunking is a backstop behind pro-fallback

Pro-fallback is the primary salvage mechanism. Sub-chunking is for the unlikely case where even pro refuses a region (severe audio corruption, long silence, language model can't parse). 3-min sub-chunks are empirically far less prone to loops than 15-min ones. Sub-chunk results concatenate naturally because they tile the original chunk's time range with zero overlap needed (we already have 30s overlap at the original chunk boundary; sub-chunks inherit that safety net).

### Real-world validation data

- `audio-05-07.ogg` (2h 18m): in current state, chunks 2 and 4 flagged with validation failures → 2 gaps totalling 7m 17s lost. Pro is expected to recover both.
- `audio-05-08.ogg` (2h 5m): chunk 2 accepted with failures → 1 gap of 3m 6s. Pro expected to recover.
- These files live at `/Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-07.ogg` and `audio-05-08.ogg`.

### What must NOT change

- Short-audio single-shot path untouched.
- Default chunked-mode behavior unchanged unless new flags are passed: **salvage is opt-in** via `--salvage` (default off). User explicitly said cost-is-no-object in their case; we should not silently burn pro tokens for everyone.
- Top-level `audioscope_TS.json` schema (legacy dict) unchanged.
- Debug dir schema unchanged — just richer `chunk_NNN.meta.json` with a new `salvage` key.

### Configuration surface

New CLI flags (all optional, all on `gski/audioscope.py` argparse setup):
- `--salvage` — enable salvage ladder (default: off)
- `--salvage-model pro` — model for pro fallback (default: `pro`)
- `--salvage-subchunk-sec 180` — sub-chunk length in seconds (default: 180 = 3 min)
- `--salvage-max-depth 2` — how many salvage steps to try (1=pro only, 2=pro+subchunk_flash, 3=pro+subchunk_flash+subchunk_pro)

---

## Task 0: Baseline check

**Files:** none

**Step 1:** Confirm branch + clean tree + tests green.

```bash
git status
python -m pytest tests/ -q
```

Expected: branch `feat/audioscope-long-audio`, 75 passed.

**Step 2:** Confirm the two real-audio smoke outputs exist for later reference:

```bash
ls /tmp/audioscope-smoke-unified-05-07/audioscope_*/merged.json
ls /tmp/audioscope-smoke-unified-05-08/audioscope_*/merged.json
```

Expected: both files exist. If not — the plan still works, just skip Task 6.

**Step 3:** No commit.

---

## Task 1: Add `_chunk_is_unhealthy` helper + tests

**Files:**
- Modify: `gski/audioscope_pipeline.py` (add helper)
- Test: `tests/test_audioscope_pipeline.py` (add tests)

**Rationale:** The salvage pass must decide which chunks need retry. Criteria: (a) `chunks_meta[i]["attempts"][-1]["ok"] is False` (accepted with validation failures) OR (b) all attempts `ok=False` AND segments contain a `chunk lost` placeholder. Keep this as a pure function so we can test it deterministically.

**Step 1: Write the failing tests**

Append to `tests/test_audioscope_pipeline.py`:

```python
def test_chunk_is_unhealthy_all_attempts_failed():
    from gski.audioscope_pipeline import _chunk_is_unhealthy
    record = {
        "index": 0,
        "attempts": [
            {"attempt": 0, "ok": False, "failed_check": "loop"},
            {"attempt": 1, "ok": False, "failed_check": "loop"},
            {"attempt": 2, "ok": False, "failed_check": "loop"},
        ],
    }
    assert _chunk_is_unhealthy(record) is True


def test_chunk_is_unhealthy_last_attempt_ok():
    from gski.audioscope_pipeline import _chunk_is_unhealthy
    record = {
        "index": 0,
        "attempts": [
            {"attempt": 0, "ok": False, "failed_check": "loop"},
            {"attempt": 1, "ok": True, "failed_check": None},
        ],
    }
    assert _chunk_is_unhealthy(record) is False


def test_chunk_is_unhealthy_no_attempts():
    from gski.audioscope_pipeline import _chunk_is_unhealthy
    assert _chunk_is_unhealthy({"index": 0, "attempts": []}) is True
```

**Step 2: Run — expect 3 failures**

```bash
python -m pytest tests/test_audioscope_pipeline.py -q -k chunk_is_unhealthy
```

Expected: `ImportError: cannot import name '_chunk_is_unhealthy'`.

**Step 3: Implement**

Add near the top of `gski/audioscope_pipeline.py`, before `transcribe_long`:

```python
def _chunk_is_unhealthy(record: dict) -> bool:
    """A chunk is unhealthy if its final retry attempt failed validation
    (accepted with failures) or no attempts succeeded at all. Used to
    drive the salvage pass."""
    attempts = record.get("attempts", [])
    if not attempts:
        return True
    return not any(a.get("ok") for a in attempts)
```

**Step 4: Run — expect 3 pass**

```bash
python -m pytest tests/test_audioscope_pipeline.py -q -k chunk_is_unhealthy
```

**Step 5: Full suite still green**

```bash
python -m pytest tests/ -q
```

Expected: 78 passed.

**Step 6: Commit**

```bash
git add gski/audioscope_pipeline.py tests/test_audioscope_pipeline.py
git commit -m "audioscope: add _chunk_is_unhealthy helper for salvage-pass selection"
```

---

## Task 2: Extract `_transcribe_chunk_with_retries` to accept an explicit model parameter (already does)

**Files:** check only

**Rationale:** Verify no refactor needed — the retry loop already takes `model` as a parameter. If yes, skip to Task 3 with no changes.

**Step 1: Inspect**

```bash
grep -n "def _transcribe_chunk_with_retries" gski/audioscope_pipeline.py
```

Read the signature. Confirm it accepts `model` (it does, per the code review in the context section). If so — proceed to Task 3. No commit.

---

## Task 3: `salvage_chunk_with_pro` — single pro retry for one failing chunk

**Files:**
- Modify: `gski/audioscope_pipeline.py`
- Test: `tests/test_audioscope_pipeline.py`

**Rationale:** Smallest possible salvage primitive. Takes one failing chunk + client + pro-model ID, re-uploads (or re-extracts and passes local path), reuses `_transcribe_chunk_with_retries` with `temperature=0.0` and the full 3-strategy retry ladder. Returns new `(segments, attempts)`.

**Step 1: Write the failing test**

Append to `tests/test_audioscope_pipeline.py`:

```python
def test_salvage_chunk_with_pro_succeeds(tmp_path):
    from gski.audioscope_pipeline import salvage_chunk_with_pro
    from gski.audioscope_utils import ChunkSpec

    audio = tmp_path / "audio.ogg"
    audio.write_bytes(b"fake")
    chunk_path = tmp_path / "chunk_000.ogg"
    chunk_path.write_bytes(b"fake")
    chunk = ChunkSpec(index=0, start=0, end=900, duration=900, path=str(chunk_path))

    client = MagicMock()
    response = MagicMock()
    response.text = (
        "["
        + ",".join(
            f'{{"s":"Speaker 1","t":"{m:02d}:00","x":"pro min {m}"}}'
            for m in range(15)
        )
        + "]"
    )
    response.candidates = [MagicMock(finish_reason="STOP")]
    response.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
    client.models.generate_content.return_value = response
    client.files.upload.return_value = MagicMock()

    segments, attempts = salvage_chunk_with_pro(
        client, chunk, model="gemini-3-pro-preview",
        diarize=True, timestamps=True, prev_tail=None,
    )
    assert len(segments) == 15
    assert segments[0]["x"] == "pro min 0"
    assert any(a.get("ok") for a in attempts)
    # First call should have used the pro model
    args, kwargs = client.models.generate_content.call_args_list[0]
    assert kwargs.get("model") == "gemini-3-pro-preview" or \
        (args and args[0] == "gemini-3-pro-preview")


def test_salvage_chunk_with_pro_still_fails_returns_best_effort(tmp_path):
    from gski.audioscope_pipeline import salvage_chunk_with_pro
    from gski.audioscope_utils import ChunkSpec

    audio = tmp_path / "audio.ogg"
    audio.write_bytes(b"fake")
    chunk_path = tmp_path / "chunk_000.ogg"
    chunk_path.write_bytes(b"fake")
    chunk = ChunkSpec(index=0, start=0, end=900, duration=900, path=str(chunk_path))

    client = MagicMock()
    # Pro also produces looped output → validation fails on all retries.
    response = MagicMock()
    response.text = '[{"s":"Speaker 1","t":"00:00","x":"loop loop loop loop loop loop loop loop loop loop"}]'
    response.candidates = [MagicMock(finish_reason="STOP")]
    response.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
    client.models.generate_content.return_value = response
    client.files.upload.return_value = MagicMock()

    segments, attempts = salvage_chunk_with_pro(
        client, chunk, model="gemini-3-pro-preview",
        diarize=True, timestamps=True, prev_tail=None,
    )
    assert not any(a.get("ok") for a in attempts)
    # Segments returned (best-effort) even if validation failed.
    assert isinstance(segments, list)
```

**Step 2: Run — expect failure (ImportError)**

```bash
python -m pytest tests/test_audioscope_pipeline.py -q -k salvage_chunk_with_pro
```

**Step 3: Implement**

Add to `gski/audioscope_pipeline.py`, near `_transcribe_chunk_with_retries`:

```python
def salvage_chunk_with_pro(
    client, chunk, *, model: str, diarize: bool, timestamps: bool, prev_tail
):
    """Retry a single chunk on the pro model using the full diverse-retry
    ladder. Returns (segments, attempts). Segments may be empty if even
    pro fails."""
    return _transcribe_chunk_with_retries(
        client,
        chunk=chunk,
        model=model,
        diarize=diarize,
        timestamps=timestamps,
        prev_tail=prev_tail,
    )
```

If the current `_transcribe_chunk_with_retries` signature differs, adjust the call site — but per Task 2 inspection it already takes keyword args of this shape.

**Step 4: Run — expect pass**

```bash
python -m pytest tests/test_audioscope_pipeline.py -q -k salvage_chunk_with_pro
```

**Step 5: Full suite**

```bash
python -m pytest tests/ -q
```

Expected: 80 passed.

**Step 6: Commit**

```bash
git add gski/audioscope_pipeline.py tests/test_audioscope_pipeline.py
git commit -m "audioscope: add salvage_chunk_with_pro — retry failing chunk on pro model"
```

---

## Task 4: `salvage_chunk_with_subchunks` — split + transcribe + stitch

**Files:**
- Modify: `gski/audioscope_pipeline.py`
- Modify: `gski/audioscope_utils.py` (maybe — only if `plan_chunks` needs a "no overlap" variant)
- Test: `tests/test_audioscope_pipeline.py`

**Rationale:** When both flash and pro fail on 15-min, chop into 5 × 3-min sub-chunks (or whatever `--salvage-subchunk-sec` says). Transcribe each on the chosen salvage model. Stitch results with timestamps shifted back to original-chunk coordinates. No overlap between sub-chunks — we trust each 3-min slice is self-contained; any boundary artefact is noise we accept given the alternative is a gap.

**Step 1: Design the stitching**

A sub-chunk covers `[sub_start, sub_end]` within the parent chunk `[chunk.start, chunk.end]`. Its segments have timestamps relative to `sub_start = 0`. To put them in the parent chunk's frame (where merge expects them relative to `chunk.start`), we shift each segment's `t` by `(sub_start - chunk.start)` seconds. After stitching all sub-chunks, the resulting segment list has timestamps relative to `chunk.start`, same convention as any other chunk's output.

**Step 2: Write the failing test**

Append:

```python
def test_salvage_chunk_with_subchunks_stitches_timestamps(tmp_path):
    from gski.audioscope_pipeline import salvage_chunk_with_subchunks
    from gski.audioscope_utils import ChunkSpec

    audio = tmp_path / "audio.ogg"
    audio.write_bytes(b"fake")
    # Parent chunk: 0..900s of the original audio.
    chunk = ChunkSpec(index=2, start=1800, end=2700, duration=900, path=str(audio))

    client = MagicMock()
    # Each sub-chunk returns 1 segment at its local time 00:10.
    call_idx = {"n": 0}
    def gen(model, contents, config):
        r = MagicMock()
        r.text = '[{"s":"Speaker 1","t":"00:10","x":"sub ' + str(call_idx["n"]) + '"}]'
        r.candidates = [MagicMock(finish_reason="STOP")]
        r.usage_metadata = MagicMock(prompt_token_count=50, candidates_token_count=10)
        call_idx["n"] += 1
        return r
    client.models.generate_content.side_effect = gen
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.extract_chunk"):
        segments, attempts = salvage_chunk_with_subchunks(
            client, chunk,
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path,
            subchunk_sec=300,  # 5 × 180-to-300... use 300 for 3 sub-chunks of 300s each
        )

    # 900s / 300s = 3 sub-chunks
    assert len(attempts) == 3
    # Each sub-chunk returned 1 segment. Total 3 segments.
    assert len(segments) == 3
    # Timestamps are relative to chunk.start=1800.
    # sub 0 local 10s → chunk-relative 10s
    # sub 1 local 10s → chunk-relative 300+10=310s
    # sub 2 local 10s → chunk-relative 600+10=610s
    from gski.audioscope_utils import parse_ts
    ts_sec = [parse_ts(s["t"]) for s in segments]
    assert ts_sec == [10, 310, 610]


def test_salvage_chunk_with_subchunks_skips_empty_sub_results(tmp_path):
    from gski.audioscope_pipeline import salvage_chunk_with_subchunks
    from gski.audioscope_utils import ChunkSpec

    audio = tmp_path / "audio.ogg"
    audio.write_bytes(b"fake")
    chunk = ChunkSpec(index=0, start=0, end=600, duration=600, path=str(audio))

    # Sub 0: returns valid seg. Sub 1: returns empty list.
    client = MagicMock()
    call_idx = {"n": 0}
    def gen(model, contents, config):
        r = MagicMock()
        r.candidates = [MagicMock(finish_reason="STOP")]
        r.usage_metadata = MagicMock(prompt_token_count=50, candidates_token_count=10)
        if call_idx["n"] == 0:
            r.text = '[{"s":"A","t":"00:05","x":"hi"}]'
        else:
            r.text = '[]'
        call_idx["n"] += 1
        return r
    client.models.generate_content.side_effect = gen
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.extract_chunk"):
        segments, attempts = salvage_chunk_with_subchunks(
            client, chunk,
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path,
            subchunk_sec=300,
        )

    assert len(segments) == 1
    assert segments[0]["x"] == "hi"
```

**Step 3: Run — expect failure**

```bash
python -m pytest tests/test_audioscope_pipeline.py -q -k salvage_chunk_with_subchunks
```

**Step 4: Implement**

Add to `gski/audioscope_pipeline.py`:

```python
def salvage_chunk_with_subchunks(
    client, chunk, *, model: str, diarize: bool, timestamps: bool,
    tmp_dir, subchunk_sec: int = 180,
):
    """Split a failed chunk into fixed-length sub-chunks (no overlap),
    transcribe each, stitch results into the parent chunk's time frame.
    Returns (segments_shifted, attempts_list)."""
    from gski.audioscope_utils import ChunkSpec, parse_ts, format_ts

    tmp_dir = Path(tmp_dir)
    all_segments: list[dict] = []
    all_attempts: list[dict] = []

    offset_in_parent = 0
    sub_idx = 0
    while offset_in_parent < chunk.duration:
        sub_len = min(subchunk_sec, chunk.duration - offset_in_parent)
        sub_path = tmp_dir / f"subchunk_{chunk.index:03d}_{sub_idx:03d}.ogg"
        # Extract from the *parent audio path* starting at chunk.start + offset.
        extract_chunk(chunk.path if chunk.path else None,  # caller passes audio path
                      chunk.start + offset_in_parent,
                      sub_len, str(sub_path))
        sub_spec = ChunkSpec(
            index=1000 * (chunk.index + 1) + sub_idx,  # distinct index space
            start=chunk.start + offset_in_parent,
            end=chunk.start + offset_in_parent + sub_len,
            duration=sub_len,
            path=str(sub_path),
        )
        sub_segments, sub_attempts = _transcribe_chunk_with_retries(
            client,
            chunk=sub_spec,
            model=model,
            diarize=diarize,
            timestamps=timestamps,
            prev_tail=None,
        )
        all_attempts.append({
            "sub_index": sub_idx,
            "offset_in_parent": offset_in_parent,
            "sub_len": sub_len,
            "attempts": sub_attempts,
            "segment_count": len(sub_segments),
        })
        # Shift timestamps from sub-local to parent-local.
        for seg in sub_segments:
            new = dict(seg)
            t = seg.get("t")
            if t:
                try:
                    new["t"] = format_ts(parse_ts(t) + offset_in_parent)
                except ValueError:
                    pass
            all_segments.append(new)
        offset_in_parent += sub_len
        sub_idx += 1

    return all_segments, all_attempts
```

**Note:** The above uses `extract_chunk(source, start, length, dest)` — confirm this matches the actual `extract_chunk` signature:

```bash
grep -n "^def extract_chunk" gski/audioscope_utils.py
```

If the signature is different, adapt the call. The important thing is extraction from the original audio file, using absolute `chunk.start + offset_in_parent` as the source offset.

**Important:** In the test, we `patch("gski.audioscope_pipeline.extract_chunk")` so the actual ffmpeg call is mocked. The `chunk.path` in test is the parent audio path; in real use, we need the **original audio path** (not the chunk's extracted path). Fix the signature: accept `audio_path` as an explicit kwarg.

Revise:

```python
def salvage_chunk_with_subchunks(
    client, chunk, *, audio_path: str, model: str, diarize: bool, timestamps: bool,
    tmp_dir, subchunk_sec: int = 180,
):
    ...
    extract_chunk(audio_path, chunk.start + offset_in_parent, sub_len, str(sub_path))
    ...
```

And update both tests to pass `audio_path=str(audio)`.

**Step 5: Run — expect pass**

```bash
python -m pytest tests/test_audioscope_pipeline.py -q -k salvage_chunk_with_subchunks
```

**Step 6: Full suite**

```bash
python -m pytest tests/ -q
```

Expected: 82 passed.

**Step 7: Commit**

```bash
git add gski/audioscope_pipeline.py tests/test_audioscope_pipeline.py
git commit -m "audioscope: add salvage_chunk_with_subchunks — split failing chunk into sub-chunks"
```

---

## Task 5: Wire salvage pass into `transcribe_long`

**Files:**
- Modify: `gski/audioscope_pipeline.py` (`transcribe_long`)
- Test: `tests/test_audioscope_pipeline.py`

**Rationale:** After the initial chunking loop, before `merge_chunks`, run a salvage pass over chunks identified by `_chunk_is_unhealthy`. Replace their `chunk_results[i]` entry in-place. Each chunk's `chunks_meta[i]` gains a `salvage` key with the ladder steps that ran.

**Step 1: Extend `transcribe_long` signature with salvage kwargs**

Add parameters (with safe defaults) to `transcribe_long`:
- `salvage: bool = False`
- `salvage_model: str = "gemini-3-pro-preview"`
- `salvage_subchunk_sec: int = 180`
- `salvage_max_depth: int = 2`

**Step 2: Write the failing integration test**

Append:

```python
def test_transcribe_long_salvage_recovers_failed_chunk_with_pro(tmp_path):
    """First flash pass: chunk 0 fails (looped). Pro salvage: chunk 0 succeeds.
    Final merged has no gap placeholders."""
    from gski.audioscope_pipeline import transcribe_long

    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"fake")

    client = MagicMock()
    call_log = []
    def gen(model, contents, config):
        call_log.append(model)
        r = MagicMock()
        r.candidates = [MagicMock(finish_reason="STOP")]
        r.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
        # Determine which chunk we're serving by looking at how many flash
        # calls have been made to chunk 0 (first 3 calls = flash retries for chunk 0,
        # next 1 call = flash for chunk 1, then pro salvage for chunk 0).
        if model == "gemini-3-flash-preview":
            # chunk 0 flash retries → always looped
            chunk0_calls = [m for m in call_log if m == "gemini-3-flash-preview"]
            if len(chunk0_calls) <= 3:
                # Simulate chunk 0 attempts 0,1,2 all looping
                r.text = '[{"s":"Speaker 1","t":"00:00","x":"loop loop loop loop loop loop loop loop loop loop"}]'
            else:
                # chunk 1 flash → succeed
                r.text = (
                    "[" + ",".join(
                        f'{{"s":"Speaker 1","t":"{m:02d}:00","x":"chunk1 min {m}"}}'
                        for m in range(15)
                    ) + "]"
                )
        else:
            # Pro salvage for chunk 0 → succeed
            r.text = (
                "[" + ",".join(
                    f'{{"s":"Speaker 1","t":"{m:02d}:00","x":"pro chunk0 min {m}"}}'
                    for m in range(15)
                ) + "]"
            )
        return r
    client.models.generate_content.side_effect = gen
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=1770), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset"):
        result = transcribe_long(
            client, audio_path=str(audio), model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
            salvage=True,
            salvage_model="gemini-3-pro-preview",
            salvage_max_depth=1,  # just pro fallback, no sub-chunking
        )

    # Pro recovered chunk 0 → segments contain "pro chunk0" prefix.
    texts = [s.get("x", "") for s in result["segments"]]
    assert any("pro chunk0" in t for t in texts), \
        f"expected pro-salvaged chunk 0 segments, got: {texts[:5]}"
    # No gap placeholders.
    assert result["coverage"]["total_untranscribed_sec"] == 0
    # chunks_meta[0] has salvage info.
    assert "salvage" in result["chunks_meta"][0]
    assert result["chunks_meta"][0]["salvage"]["pro"]["ok"] is True


def test_transcribe_long_salvage_falls_back_to_subchunk(tmp_path):
    """Pro also fails → subchunk pass recovers."""
    from gski.audioscope_pipeline import transcribe_long

    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"fake")

    client = MagicMock()
    def gen(model, contents, config):
        r = MagicMock()
        r.candidates = [MagicMock(finish_reason="STOP")]
        r.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
        # flash & pro on 15-min → always loop
        # flash on 3-min sub-chunks → success, one seg per sub-chunk
        # Heuristic: if this call's contents audio file has "subchunk" in path → success
        # But we mocked extract_chunk so files don't actually exist. Use content inspection
        # isn't reliable — use a call counter instead.
        # Simpler: count flash calls. First 3 are chunk 0 retries. Pro calls next 3 are pro retries on chunk 0.
        # Any subsequent flash call on sub-chunks succeeds.
        count = client.models.generate_content.call_count
        if count <= 6:  # 3 flash + 3 pro → all fail
            r.text = '[{"s":"Speaker 1","t":"00:00","x":"loop loop loop loop loop loop loop loop loop loop"}]'
        else:
            r.text = f'[{{"s":"Speaker 1","t":"00:05","x":"subchunk seg {count}"}}]'
        return r
    client.models.generate_content.side_effect = gen
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=900), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset"):
        result = transcribe_long(
            client, audio_path=str(audio), model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
            salvage=True,
            salvage_model="gemini-3-pro-preview",
            salvage_subchunk_sec=300,
            salvage_max_depth=2,
        )

    texts = [s.get("x", "") for s in result["segments"]]
    assert any("subchunk seg" in t for t in texts)
    assert result["chunks_meta"][0]["salvage"]["subchunk_flash"]["segment_count"] >= 1


def test_transcribe_long_salvage_disabled_by_default(tmp_path):
    """Without --salvage, unhealthy chunks stay unhealthy."""
    from gski.audioscope_pipeline import transcribe_long

    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"fake")

    client = MagicMock()
    response = MagicMock()
    response.text = '[{"s":"Speaker 1","t":"00:00","x":"loop loop loop loop loop loop loop loop loop loop"}]'
    response.candidates = [MagicMock(finish_reason="STOP")]
    response.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
    client.models.generate_content.return_value = response
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=900), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset"):
        result = transcribe_long(
            client, audio_path=str(audio), model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
            # salvage=False by default
        )

    # No pro calls were made.
    models_called = [c.kwargs.get("model") or c.args[0] if c.args else None
                     for c in client.models.generate_content.call_args_list]
    assert "gemini-3-pro-preview" not in models_called
    # chunks_meta has no salvage key (or has salvage={"enabled": False}).
    assert not result["chunks_meta"][0].get("salvage", {}).get("pro")
```

**Step 3: Run — expect failures**

```bash
python -m pytest tests/test_audioscope_pipeline.py -q -k "salvage and transcribe_long"
```

**Step 4: Implement salvage loop in `transcribe_long`**

After the existing chunking loop, before `merged = merge_chunks(chunk_results)`, insert:

```python
    if salvage:
        for i, record in enumerate(chunks_meta):
            if not _chunk_is_unhealthy(record):
                continue
            chunk, _orig_segments = chunk_results[i]
            ladder_results = {}

            # Step 1: pro fallback on full chunk
            if salvage_max_depth >= 1:
                pro_segs, pro_attempts = salvage_chunk_with_pro(
                    client, chunk,
                    model=salvage_model,
                    diarize=diarize, timestamps=timestamps,
                    prev_tail=None,
                )
                pro_ok = any(a.get("ok") for a in pro_attempts)
                ladder_results["pro"] = {
                    "ok": pro_ok,
                    "segment_count": len(pro_segs),
                    "attempts": pro_attempts,
                }
                if pro_ok:
                    chunk_results[i] = (chunk, pro_segs)
                    record["salvage"] = ladder_results
                    warnings.append(
                        f"chunk {chunk.index} salvaged via pro-fallback "
                        f"({len(pro_segs)} segments)"
                    )
                    continue

            # Step 2: sub-chunk with flash
            if salvage_max_depth >= 2:
                sub_segs, sub_attempts = salvage_chunk_with_subchunks(
                    client, chunk,
                    audio_path=audio_path,
                    model=model,  # flash
                    diarize=diarize, timestamps=timestamps,
                    tmp_dir=tmp_dir,
                    subchunk_sec=salvage_subchunk_sec,
                )
                ladder_results["subchunk_flash"] = {
                    "segment_count": len(sub_segs),
                    "sub_attempts": sub_attempts,
                }
                if sub_segs:
                    chunk_results[i] = (chunk, sub_segs)
                    record["salvage"] = ladder_results
                    warnings.append(
                        f"chunk {chunk.index} salvaged via flash sub-chunking "
                        f"({len(sub_segs)} segments)"
                    )
                    continue

            # Step 3: sub-chunk with pro
            if salvage_max_depth >= 3:
                sub_segs, sub_attempts = salvage_chunk_with_subchunks(
                    client, chunk,
                    audio_path=audio_path,
                    model=salvage_model,
                    diarize=diarize, timestamps=timestamps,
                    tmp_dir=tmp_dir,
                    subchunk_sec=salvage_subchunk_sec,
                )
                ladder_results["subchunk_pro"] = {
                    "segment_count": len(sub_segs),
                    "sub_attempts": sub_attempts,
                }
                if sub_segs:
                    chunk_results[i] = (chunk, sub_segs)
                    record["salvage"] = ladder_results
                    warnings.append(
                        f"chunk {chunk.index} salvaged via pro sub-chunking "
                        f"({len(sub_segs)} segments)"
                    )
                    continue

            # All salvage steps exhausted — leave chunk as-is.
            record["salvage"] = ladder_results
            warnings.append(
                f"chunk {chunk.index} salvage FAILED (depth={salvage_max_depth}); leaving as-is"
            )

        # Re-write updated meta files after salvage.
        for i, record in enumerate(chunks_meta):
            (run_dir / f"chunk_{record['index']:03d}.meta.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=False, default=str)
            )
```

**Step 5: Run — expect pass**

```bash
python -m pytest tests/test_audioscope_pipeline.py -q -k "salvage and transcribe_long"
```

**Step 6: Full suite**

```bash
python -m pytest tests/ -q
```

Expected: 85 passed.

**Step 7: Commit**

```bash
git add gski/audioscope_pipeline.py tests/test_audioscope_pipeline.py
git commit -m "audioscope: salvage pass in transcribe_long — pro fallback + sub-chunking"
```

---

## Task 6: Expose salvage flags on CLI

**Files:**
- Modify: `gski/audioscope.py` (argparse + call to `transcribe_long`)

**Step 1: Add argparse flags**

In `gski/audioscope.py`, find the argparse section (around lines 170–230, look for `add_argument("--chunk-len-sec"`). Add after the existing chunking flags:

```python
    ap.add_argument(
        "--salvage", action="store_true",
        help="enable salvage pass for failed chunks (pro fallback + sub-chunking)",
    )
    ap.add_argument(
        "--salvage-model", default="pro", choices=list(MODELS),
        help="model for salvage pro-fallback (default: pro)",
    )
    ap.add_argument(
        "--salvage-subchunk-sec", type=int, default=180,
        help="sub-chunk length in seconds for salvage (default: 180)",
    )
    ap.add_argument(
        "--salvage-max-depth", type=int, default=2,
        help="salvage ladder depth: 1=pro only, 2=+flash subchunk, 3=+pro subchunk (default: 2)",
    )
```

**Step 2: Thread flags into `transcribe_long` call**

In `run()`, in the chunked branch, update the `transcribe_long()` call:

```python
                result = transcribe_long(
                    client,
                    audio_path=args.audio[0],
                    model=model,
                    diarize=args.diarize,
                    timestamps=args.timestamps,
                    chunk_len_sec=args.chunk_len_sec,
                    overlap_sec=args.overlap_sec,
                    tmp_dir=tmp_dir,
                    output_dir=output_dir,
                    salvage=args.salvage,
                    salvage_model=MODELS[args.salvage_model],
                    salvage_subchunk_sec=args.salvage_subchunk_sec,
                    salvage_max_depth=args.salvage_max_depth,
                )
```

**Step 3: Update the existing short-path regression test to include the new flags with defaults**

In `tests/test_audioscope_short_path.py`, the `types.SimpleNamespace(...)` constructors must include the new attrs (`salvage=False`, `salvage_model="pro"`, `salvage_subchunk_sec=180`, `salvage_max_depth=2`) because `run()` will now read them. Similarly for the chunked CLI integration test in `tests/test_audioscope_pipeline.py`.

**Step 4: Run full suite**

```bash
python -m pytest tests/ -q
```

Expected: 85 passed. If any test fails with `AttributeError: 'SimpleNamespace' object has no attribute 'salvage'`, add the missing kwargs to that test's namespace.

**Step 5: Commit**

```bash
git add gski/audioscope.py tests/test_audioscope_short_path.py tests/test_audioscope_pipeline.py
git commit -m "audioscope: expose --salvage, --salvage-model, --salvage-subchunk-sec, --salvage-max-depth"
```

---

## Task 7: Real-audio smoke — 05-07 with `--salvage`

**Files:** none (runtime check only)

**Rationale:** 05-07 has two validated gaps in current output. Salvage should close them.

**Step 1: Run**

```bash
rm -rf /tmp/audioscope-salvage-05-07
gski audioscope \
  --audio /Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-07.ogg \
  --diarize --timestamps --model flash \
  --salvage \
  --output-dir /tmp/audioscope-salvage-05-07 \
  2>&1 | tail -30
```

Expected output includes:
- Original warnings about chunk 2 and 4 flash failures
- Salvage lines: `chunk 2 salvaged via pro-fallback (N segments)`
- `chunk 4 salvaged via pro-fallback (M segments)`
- Final `coverage:` warning absent OR coverage total_untranscribed_sec = 0

**Step 2: Verify coverage**

```bash
python3 -c "
import json, glob
p = glob.glob('/tmp/audioscope-salvage-05-07/audioscope_*.json')[0]
d = json.load(open(p))
sys_segs = [s for s in d['segments'] if s['speaker'] == '__system__']
print(f'segments: {len(d[\"segments\"])}')
print(f'system markers: {len(sys_segs)}')
for s in sys_segs:
    print(f'  [{s[\"timestamp\"]}] {s[\"content\"][:80]}')
"
```

Expected: 0 system markers, or strictly fewer than 2. If still 2 — pro didn't help (unlikely on Russian meeting audio); investigate per-chunk meta at `/tmp/audioscope-salvage-05-07/audioscope_*/chunk_002.meta.json`.

**Step 3: Verify segment count didn't drop**

```bash
python3 -c "
import json, glob
old = json.load(open(glob.glob('/tmp/audioscope-smoke-unified-05-07/audioscope_*.json')[0]))
new = json.load(open(glob.glob('/tmp/audioscope-salvage-05-07/audioscope_*.json')[0]))
print(f'old segments: {len(old[\"segments\"])}')
print(f'new segments: {len(new[\"segments\"])}')
print(f'old untranscribed: {old.get(\"coverage\", {}).get(\"total_untranscribed_sec\", \"n/a\")}')
"
```

Expected: new ≥ old (salvage should add segments, not remove).

**Step 4: No commit.** If any assertion fails, stop and ask the user.

---

## Task 8: Real-audio smoke — 05-08 with `--salvage`

Repeat Task 7 with `/Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-08.ogg` and `/tmp/audioscope-salvage-05-08`. Expected: 1 gap closed (186s currently untranscribed).

---

## Task 9: Update SKILL.md

**Files:**
- Modify: `gski/skills/audioscope/SKILL.md`

**Step 1: Add a "Salvage" subsection after the "Output layout" section**

Append:

```markdown
## Salvage mode

Opt-in, for when you cannot tolerate untranscribed segments. Adds significant
API cost (pro model is ~10× flash).

```
--salvage                     enable salvage ladder (default: off)
--salvage-model pro           model for pro fallback (default: pro)
--salvage-subchunk-sec 180    sub-chunk length in seconds (default: 180)
--salvage-max-depth 2         ladder depth 1-3 (default: 2)
```

When enabled, after the initial chunking pass, any chunk that failed all
flash retries is retried on the salvage model (default: pro). If pro also
fails, the chunk is split into `salvage-subchunk-sec`-long slices and
each is transcribed separately on flash. Depth 3 adds a pro pass over
the sub-chunks as a final backstop.

Per-chunk salvage metadata is recorded in `chunk_NNN.meta.json` under
a new `salvage` key. Stderr prints one line per recovered chunk:
`chunk N salvaged via pro-fallback (M segments)`.
```

**Step 2: Commit**

```bash
git add gski/skills/audioscope/SKILL.md
git commit -m "audioscope: document --salvage mode (pro-fallback + sub-chunking)"
```

---

## Completion criteria

- [ ] 85+ tests green (75 pre-existing + 3 `_chunk_is_unhealthy` + 2 `salvage_chunk_with_pro` + 2 `salvage_chunk_with_subchunks` + 3 `transcribe_long_salvage`)
- [ ] `--salvage` recovers real-world 05-07 gaps (both or one of them)
- [ ] `--salvage` recovers real-world 05-08 gap
- [ ] Default behaviour (no `--salvage` flag) byte-identical to pre-plan — same warnings, same output files, no extra API calls
- [ ] SKILL.md documents the new flags

## Out of scope

- Mixing salvage results with partial original segments (e.g. taking the first 8 good minutes from flash and salvaging only the last 7 with pro) — harder boundary stitching, YAGNI until we see a case where pro fails too
- Cost tracking / API budget limits — user is cost-insensitive in target use case
- Salvage on the short-audio path — that path is single-shot, no chunks to salvage
- Parallel salvage pass (running pro for multiple failed chunks concurrently) — Python `google-genai` client is sync; would need threading; YAGNI while 1-2 failing chunks per 2h audio is the observed rate

---

## For the executing agent — handoff notes

1. This plan is larger than Part 2 unification: ~9 tasks, ~2-3 hours with tests and two real-audio smokes.
2. Worktree: `/Users/iz/work/gski/.worktrees/audioscope-long-audio`. Branch: `feat/audioscope-long-audio`.
3. Tasks 7 and 8 each make real API calls on ~2h audio — the salvage pass will at minimum add 3 extra pro calls per failing chunk. Expect 15-25 extra minutes runtime per test. Run sequentially (user specified).
4. After Task 9, run full suite once more, then use `finishing-a-development-branch` skill.
5. Don't modify files outside `gski/` and `tests/` except `gski/skills/audioscope/SKILL.md`.
