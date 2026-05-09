# Audioscope Chunked-Mode Unified Output Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the long-audio chunked path produce the same user-visible artifact as the short-audio path — a single `audioscope_TS.json` in the old dict schema that downstream consumers (`meet-transcribe`, `vm-transcribe`) already glob for.

**Architecture:** Keep the existing debug directory `audioscope_TS/` (with `merged.json`, `chunk_*.meta.json`, `chunk_*.raw.txt`) exactly as-is for diagnostics. Additionally write, alongside it in `output-dir/`, a top-level `audioscope_TS.json` file in the same dict shape short-mode produces (`{"summary": "...", "segments": [{speaker, timestamp, content}, ...]}`). A converter function translates the flat merge schema `{s,t,x}` to the legacy dict schema. The top-level `.json` filename matches the debug dir base name (shared timestamp), so one `ls output/` shows one artifact and one debug dir per run — mirroring short-mode which produces `audioscope_TS.json` + `audioscope_TS.raw.txt`.

**Tech Stack:** Python 3.14, pytest, existing `gski.audioscope`, `gski.audioscope_pipeline`, `gski.audioscope_utils`.

---

## Context the executing agent needs

### Current behaviour

**Short-audio diarize path** (`gski/audioscope.py` lines ~298–337, in `run()`):
- Writes `output_dir/audioscope_TS.raw.txt` (raw Gemini response)
- Writes `output_dir/audioscope_TS.json` — parsed JSON, shape: `{"summary": "...", "segments": [{"speaker":"Speaker 1","timestamp":"00:05","content":"hi"}, ...]}` (old schema via `DIARIZE_TS_SCHEMA`)
- Prints `format_diarize(data)` to stdout
- Prints `saved: <json_path>` to stderr

**Long-audio chunked path** (`gski/audioscope.py` lines ~258–296, in `run()`):
- Delegates to `transcribe_long()` in `gski/audioscope_pipeline.py` which creates `output_dir/audioscope_TS/` and writes `merged.json` + `chunk_*.meta.json` + `chunk_*.raw.txt` inside it
- `merged.json` shape: flat array `[{"s":"Speaker 1","t":"00:05","x":"hi"}, ...]` (new flat schema via `FLAT_DIARIZE_TS_SCHEMA`)
- Prints `format_diarize(result["segments"])` to stdout
- Prints `saved: <run_dir>` to stderr (points at the directory, not a .json file)

### Downstream consumers that must keep working

`/Users/iz/work/scripts/meet-transcribe` line 131 and `/Users/iz/work/scripts/vm-transcribe` line 112 both do:
```python
json_files = list(Path(output_dir).glob("*.json"))
# ...
data = json.load(open(json_files[0]))
# ...
for seg in data.get("segments", []):
    sp = seg.get("speaker", "Unknown")
    ts = seg.get("timestamp", "")
    content = seg.get("content", "")
```

These scripts currently **fail on long audio** because `output_dir` contains only a subdirectory (`audioscope_TS/`) with `merged.json` inside — `glob("*.json")` returns empty.

### Key schema contract to preserve

The top-level file **must** have keys `speaker`, `timestamp`, `content` (not `s`, `t`, `x`). It must be a dict (not a list) with top-level `segments` key. `summary` can be empty string.

### System segments from Part 2

`merged.json` may contain `{"s": "__system__", ...}` entries for gap/lost-chunk markers. These must be converted too (speaker `"__system__"` stays as-is in the legacy format — downstream scripts will render it through their own formatters; if they don't handle it they'll print `__system__` as a speaker name, which is acceptable).

---

## Task 0: Verify starting point (no changes)

**Files:** none

**Step 1: Confirm branch and clean tree**

```bash
git status
git log --oneline -n 5
```

Expected: on branch `feat/audioscope-long-audio` (or wherever user resumes), working tree clean. Last commits relate to audioscope Part 2 (smoke v3, placeholders, salvage, diverse retries).

**Step 2: Run current test suite — must all pass before any change**

```bash
python -m pytest tests/ -q
```

Expected: **65 passed**. If fewer, stop and ask the user — the baseline is broken.

**Step 3: No commit** (nothing changed).

---

## Task 1: Add schema converter `flat_segments_to_legacy_dict`

**Files:**
- Modify: `gski/audioscope_pipeline.py` (add new helper)
- Test: `tests/test_audioscope_pipeline.py` (add new tests)

**Rationale:** Converting happens on the boundary between pipeline and CLI. Putting it in `audioscope_pipeline.py` keeps it next to `merge_chunks` and avoids polluting `audioscope.py` (which already imports from pipeline).

**Step 1: Write the failing test**

Append to `tests/test_audioscope_pipeline.py`:

```python
def test_flat_to_legacy_converts_keys_and_wraps_in_dict():
    from gski.audioscope_pipeline import flat_segments_to_legacy_dict
    flat = [
        {"s": "Speaker 1", "t": "00:05", "x": "hello"},
        {"s": "Speaker 2", "t": "00:14", "x": "world"},
    ]
    out = flat_segments_to_legacy_dict(flat)
    assert isinstance(out, dict)
    assert out.get("summary") == ""
    assert out["segments"] == [
        {"speaker": "Speaker 1", "timestamp": "00:05", "content": "hello"},
        {"speaker": "Speaker 2", "timestamp": "00:14", "content": "world"},
    ]


def test_flat_to_legacy_preserves_system_speaker():
    from gski.audioscope_pipeline import flat_segments_to_legacy_dict
    flat = [
        {"s": "__system__", "t": "47:33", "x": "[\u2026gap: 14m 53s untranscribed\u2026]"},
    ]
    out = flat_segments_to_legacy_dict(flat)
    assert out["segments"][0]["speaker"] == "__system__"
    assert out["segments"][0]["content"].startswith("[\u2026gap:")


def test_flat_to_legacy_handles_missing_timestamp():
    from gski.audioscope_pipeline import flat_segments_to_legacy_dict
    flat = [{"s": "A", "x": "no ts here"}]  # t missing (diarize without timestamps)
    out = flat_segments_to_legacy_dict(flat)
    # timestamp should be "" rather than missing key, for downstream .get() safety
    assert out["segments"][0]["timestamp"] == ""
    assert out["segments"][0]["speaker"] == "A"
    assert out["segments"][0]["content"] == "no ts here"


def test_flat_to_legacy_empty_list():
    from gski.audioscope_pipeline import flat_segments_to_legacy_dict
    out = flat_segments_to_legacy_dict([])
    assert out == {"summary": "", "segments": []}
```

**Step 2: Run — expect 4 failures (function doesn't exist)**

```bash
python -m pytest tests/test_audioscope_pipeline.py -q -k flat_to_legacy
```

Expected: 4 failures, all `ImportError: cannot import name 'flat_segments_to_legacy_dict'`.

**Step 3: Implement**

Add to `gski/audioscope_pipeline.py`, at module level (after imports, before `_ANTI_LOOP_PROMPT_SUFFIX` or anywhere — suggest near bottom, after `transcribe_long`):

```python
def flat_segments_to_legacy_dict(segments: list[dict]) -> dict:
    """Convert flat {s,t,x} segments to the legacy dict schema
    {"summary": ..., "segments": [{speaker, timestamp, content}, ...]}
    used by short-audio path and downstream consumers (meet-transcribe,
    vm-transcribe). Keeps __system__ speaker token as-is."""
    out = []
    for seg in segments:
        out.append({
            "speaker": seg.get("s", ""),
            "timestamp": seg.get("t", ""),
            "content": seg.get("x", ""),
        })
    return {"summary": "", "segments": out}
```

**Step 4: Run — expect all 4 pass**

```bash
python -m pytest tests/test_audioscope_pipeline.py -q -k flat_to_legacy
```

Expected: 4 passed.

**Step 5: Run full suite — nothing else broken**

```bash
python -m pytest tests/ -q
```

Expected: 69 passed (65 + 4 new).

**Step 6: Commit**

```bash
git add gski/audioscope_pipeline.py tests/test_audioscope_pipeline.py
git commit -m "audioscope: add flat→legacy schema converter for unified CLI output"
```

---

## Task 2: Make chunked CLI path write legacy `.json` alongside debug dir

**Files:**
- Modify: `gski/audioscope.py` (chunked branch in `run()`)

**Rationale:** Minimal CLI change. After `transcribe_long()` returns, extract the run-dir basename (e.g. `audioscope_20260509_121455`) and write a sibling `.json` file in `output_dir`. Do NOT change the stdout format (`format_diarize` still prints the flat segments).

**Step 1: Write the failing test**

This needs an integration-style test that invokes the CLI `run()` for the chunked path. Append to `tests/test_audioscope_pipeline.py`:

```python
def test_cli_chunked_writes_legacy_json_at_output_root(tmp_path, monkeypatch):
    """In chunked mode, output_dir must contain a top-level audioscope_TS.json
    alongside the audioscope_TS/ debug directory."""
    import types
    from gski import audioscope as cli

    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    out_dir = tmp_path / "out"

    # Fake Gemini client: 2 chunks, both succeed with dense per-minute segments.
    client = MagicMock()
    def fake_generate(model, contents, config):
        r = MagicMock()
        r.candidates = [MagicMock(finish_reason="STOP")]
        r.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
        idx = client.models.generate_content.call_count - 1
        segs = [
            f'{{"s":"Speaker 1","t":"{m:02d}:00","x":"chunk {idx} min {m}"}}'
            for m in range(15)
        ]
        r.text = "[" + ",".join(segs) + "]"
        return r
    client.models.generate_content.side_effect = fake_generate
    client.files.upload.return_value = MagicMock()

    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    # Fake args namespace (the exact shape argparse produces)
    args = types.SimpleNamespace(
        prompt=None, audio=[str(audio)], youtube=[], model="flash",
        diarize=True, timestamps=True, output_dir=str(out_dir),
        chunk_len_sec=900, overlap_sec=30, no_chunking=False,
    )

    with patch("gski.audioscope.genai.Client", return_value=client), \
         patch("gski.audioscope_pipeline.probe_duration", return_value=1770), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset"):
        cli.run(args)

    # There must be exactly one top-level .json plus one debug dir.
    top_json = list(out_dir.glob("audioscope_*.json"))
    debug_dirs = [p for p in out_dir.iterdir() if p.is_dir() and p.name.startswith("audioscope_")]
    assert len(top_json) == 1, f"expected 1 top-level json, got {top_json}"
    assert len(debug_dirs) == 1, f"expected 1 debug dir, got {debug_dirs}"
    # Top-level json and debug dir share the same TS base name.
    assert top_json[0].stem == debug_dirs[0].name

    # Content: legacy dict schema, not flat list.
    data = json.loads(top_json[0].read_text())
    assert isinstance(data, dict)
    assert "segments" in data
    assert data["segments"]
    first = data["segments"][0]
    assert set(first.keys()) >= {"speaker", "timestamp", "content"}
    # downstream-consumer smoke: .get('speaker'), .get('content'), .get('timestamp')
    assert first["speaker"] == "Speaker 1"
    assert first["content"].startswith("chunk 0 min")
```

Also add `import json` at the top of that test file if not already imported. Check with:

```bash
head -5 tests/test_audioscope_pipeline.py
```

If `import json` is missing, add it.

**Step 2: Run — expect failure (no top-level json written)**

```bash
python -m pytest tests/test_audioscope_pipeline.py::test_cli_chunked_writes_legacy_json_at_output_root -v
```

Expected: `AssertionError: expected 1 top-level json, got []`.

**Step 3: Implement**

Modify `gski/audioscope.py` in the chunked branch. Current code (around lines 280–296):

```python
            with tempfile.TemporaryDirectory(prefix="audioscope_chunks_") as tmp_dir:
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
                )
            print(format_diarize(result["segments"]))
            for w in result["warnings"]:
                print(f"warning: {w}", file=sys.stderr)
            print(f"\nsaved: {result['run_dir']}", file=sys.stderr)
            return
```

Replace the block from `print(format_diarize(...))` through `return` with:

```python
            # Write top-level legacy-shape JSON alongside the debug run dir, so
            # downstream consumers (meet-transcribe, vm-transcribe) that
            # glob output_dir/*.json keep working.
            from gski.audioscope_pipeline import flat_segments_to_legacy_dict
            run_dir_path = Path(result["run_dir"])
            legacy_json_path = output_dir / f"{run_dir_path.name}.json"
            legacy = flat_segments_to_legacy_dict(result["segments"])
            legacy_json_path.write_text(
                json.dumps(legacy, indent=2, ensure_ascii=False)
            )

            print(format_diarize(result["segments"]))
            for w in result["warnings"]:
                print(f"warning: {w}", file=sys.stderr)
            print(f"\nsaved: {legacy_json_path}", file=sys.stderr)
            print(f"debug artifacts: {run_dir_path}", file=sys.stderr)
            return
```

Note: `Path` is already imported at top of `gski/audioscope.py`; `json` is already imported; no new top-level imports needed.

**Step 4: Run — expect pass**

```bash
python -m pytest tests/test_audioscope_pipeline.py::test_cli_chunked_writes_legacy_json_at_output_root -v
```

Expected: PASSED.

**Step 5: Run full suite**

```bash
python -m pytest tests/ -q
```

Expected: 70 passed.

**Step 6: Commit**

```bash
git add gski/audioscope.py tests/test_audioscope_pipeline.py
git commit -m "audioscope: chunked mode writes top-level legacy JSON for downstream consumers"
```

---

## Task 3: Regression test — short-audio path still behaves the same

**Files:**
- Test: `tests/test_audioscope_short_path.py` (new file)

**Rationale:** No change to short-audio behaviour should be caused by Task 2. Add an explicit test so a future refactor can't silently break short-mode.

**Step 1: Create `tests/test_audioscope_short_path.py`**

```python
import json
import types
from unittest.mock import MagicMock, patch

from gski import audioscope as cli


def test_cli_short_diarize_writes_flat_json_and_raw(tmp_path, monkeypatch):
    """Short-audio diarize path is untouched: one .json + one .raw.txt at
    output root, no subdirectory."""
    audio = tmp_path / "short.ogg"
    audio.write_bytes(b"fake")
    out_dir = tmp_path / "out"

    client = MagicMock()
    response = MagicMock()
    response.text = json.dumps({
        "summary": "short chat",
        "segments": [
            {"speaker": "Speaker 1", "timestamp": "00:05", "content": "hi"},
            {"speaker": "Speaker 2", "timestamp": "00:10", "content": "hey"},
        ],
    })
    client.models.generate_content.return_value = response
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    args = types.SimpleNamespace(
        prompt=None, audio=[str(audio)], youtube=[], model="flash",
        diarize=True, timestamps=True, output_dir=str(out_dir),
        chunk_len_sec=900, overlap_sec=30, no_chunking=False,
    )

    # Make probe_duration return something small so chunked path is NOT taken.
    with patch("gski.audioscope.genai.Client", return_value=client), \
         patch("gski.audioscope.probe_duration", return_value=60.0) if False else \
         patch("gski.audioscope_utils.probe_duration", return_value=60.0):
        cli.run(args)

    # Exactly one .json and one .raw.txt at output root. No subdirs.
    jsons = list(out_dir.glob("*.json"))
    raws = list(out_dir.glob("*.raw.txt"))
    subdirs = [p for p in out_dir.iterdir() if p.is_dir()]
    assert len(jsons) == 1, f"expected 1 json, got {jsons}"
    assert len(raws) == 1, f"expected 1 raw.txt, got {raws}"
    assert len(subdirs) == 0, f"expected no subdirs in short mode, got {subdirs}"

    # Legacy schema preserved.
    data = json.loads(jsons[0].read_text())
    assert data["segments"][0]["speaker"] == "Speaker 1"
    assert data["segments"][0]["content"] == "hi"


def test_cli_no_chunking_flag_forces_short_path(tmp_path, monkeypatch):
    """--no-chunking forces short path even if audio would be long."""
    audio = tmp_path / "long.ogg"
    audio.write_bytes(b"fake")
    out_dir = tmp_path / "out"

    client = MagicMock()
    response = MagicMock()
    response.text = json.dumps({"summary": "", "segments": [
        {"speaker": "A", "timestamp": "00:00", "content": "x"},
    ]})
    client.models.generate_content.return_value = response
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    args = types.SimpleNamespace(
        prompt=None, audio=[str(audio)], youtube=[], model="flash",
        diarize=True, timestamps=True, output_dir=str(out_dir),
        chunk_len_sec=900, overlap_sec=30, no_chunking=True,  # <-- key
    )

    # Duration 2h+ but --no-chunking should skip chunked path.
    with patch("gski.audioscope.genai.Client", return_value=client), \
         patch("gski.audioscope_utils.probe_duration", return_value=7500.0):
        cli.run(args)

    subdirs = [p for p in out_dir.iterdir() if p.is_dir()]
    assert not subdirs, f"no-chunking must not create debug dir, got {subdirs}"
    assert list(out_dir.glob("*.json")), "short-mode json must still be produced"
```

**Step 2: Review lint-ish issue**

The `patch(...) if False else patch(...)` pattern is ugly — rewrite the short-path test more cleanly:

```python
    with patch("gski.audioscope.genai.Client", return_value=client), \
         patch("gski.audioscope_utils.probe_duration", return_value=60.0):
        cli.run(args)
```

(Replace the `if False` block accordingly before running.)

**Step 3: Run**

```bash
python -m pytest tests/test_audioscope_short_path.py -v
```

Expected: 2 passed. If either fails, the task 2 change accidentally altered short-mode — read the diff and fix.

**Step 4: Run full suite**

```bash
python -m pytest tests/ -q
```

Expected: 72 passed.

**Step 5: Commit**

```bash
git add tests/test_audioscope_short_path.py
git commit -m "audioscope: regression test — short-audio path unchanged by chunked unification"
```

---

## Task 4: Smoke against existing 2h output (offline verification)

**Files:** none

**Rationale:** The user already has a fresh 2h smoke-test output on disk from the previous session at `/tmp/audioscope-smoke-05-08-v3/audioscope_20260509_121455/merged.json`. Simulate the new CLI output by running the converter and verifying downstream parseability — no new API calls required.

**Step 1: Run converter over existing merged.json**

```bash
python3 <<'PY'
import json, glob
from gski.audioscope_pipeline import flat_segments_to_legacy_dict

p = "/tmp/audioscope-smoke-05-08-v3/audioscope_20260509_121455/merged.json"
flat = json.load(open(p))
legacy = flat_segments_to_legacy_dict(flat)

# Simulate what meet-transcribe/vm-transcribe will do.
data = legacy
segs = data.get("segments", [])
print(f"segments: {len(segs)}")
print(f"first: {segs[0]}")
print(f"last: {segs[-1]}")

# Both scripts iterate these keys:
for seg in segs[:3]:
    sp = seg.get("speaker", "Unknown")
    ts = seg.get("timestamp", "")
    content = seg.get("content", "")
    assert sp, f"missing speaker: {seg}"
    assert content, f"missing content: {seg}"
    print(f"[{ts}] {sp}: {content[:60]}")

# System markers still readable
sys_segs = [s for s in segs if s.get("speaker") == "__system__"]
print(f"system markers: {len(sys_segs)}")
print("OK — legacy schema is consumable by meet-transcribe/vm-transcribe")
PY
```

Expected: prints segment counts, system markers (0 for 05-08, 2 for 05-07), no assertion errors.

**Step 2: (Optional) Also verify on 05-07 output**

Repeat with `/tmp/audioscope-smoke-05-07-v3/audioscope_20260509_122325/merged.json`. Expect 2 `__system__` segments with `speaker == "__system__"`.

**Step 3: No commit** (no file changes).

---

## Task 5: Update SKILL.md — document the new file layout

**Files:**
- Modify: `gski/skills/audioscope/SKILL.md`

**Step 1: Inspect current SKILL.md chunking section**

```bash
grep -n -A 20 -i "chunking\|output\|chunked" gski/skills/audioscope/SKILL.md | head -60
```

**Step 2: Edit — clarify the output layout for chunked mode**

Find the section describing output layout (should already mention chunking in some form). Replace or add a subsection:

```markdown
## Output layout

**All modes produce** `<output-dir>/audioscope_<TS>.json` — legacy dict shape
`{"summary": "", "segments": [{"speaker": "...", "timestamp": "...", "content": "..."}, ...]}`.
This is the file downstream scripts should read.

**Diarize short-audio mode** additionally writes `audioscope_<TS>.raw.txt`
(raw Gemini response, used for debugging parse failures).

**Diarize long-audio mode** (>~16 min, auto-triggered) additionally writes a
debug directory `audioscope_<TS>/` containing:
- `merged.json` — same segments in flat `{s,t,x}` schema
- `chunk_NNN.meta.json` — per-chunk retry attempts, strategies, validation reasons
- `chunk_NNN.raw.txt` — raw Gemini response for the last attempt of each chunk

Downstream consumers (meet-transcribe, vm-transcribe) see one `.json`
per run at the output root regardless of chunked/non-chunked mode — they
do not need to know which path was taken.

The system speaker `__system__` is used for gap/lost-chunk placeholders
injected automatically when the model skips audio or a chunk fails all
retries. Downstream formatters can filter these out or render them
distinctly; they are semantically "transcript coverage metadata", not
real speech.
```

**Step 3: Commit**

```bash
git add gski/skills/audioscope/SKILL.md
git commit -m "audioscope: document unified output layout and system-speaker semantics"
```

---

## Task 6: Optional manual smoke — re-run on audio-05-08 if time permits

**Files:** none

**Rationale:** Offline smoke in Task 4 proves the converter output, but does not prove the new CLI write path actually creates the `.json` for a real run. Optional, takes ~10 min.

**Step 1: Run**

```bash
rm -rf /tmp/audioscope-smoke-unified
gski audioscope \
  --audio /Users/iz/work/tasks/google-meet-transcribe/tests/audio-05-08.ogg \
  --diarize --timestamps --model flash \
  --output-dir /tmp/audioscope-smoke-unified \
  2>&1 | tail -20
```

**Step 2: Verify layout**

```bash
ls -la /tmp/audioscope-smoke-unified/
```

Expected:
- exactly one `audioscope_YYYYMMDD_HHMMSS.json` file (legacy dict schema)
- exactly one `audioscope_YYYYMMDD_HHMMSS/` directory (debug artefacts)
- basenames identical

**Step 3: Verify downstream-consumer compatibility**

```bash
python3 -c "
import json, glob
p = glob.glob('/tmp/audioscope-smoke-unified/audioscope_*.json')[0]
data = json.load(open(p))
assert isinstance(data, dict) and 'segments' in data
seg0 = data['segments'][0]
assert 'speaker' in seg0 and 'timestamp' in seg0 and 'content' in seg0
print('OK —', len(data['segments']), 'segments, first:', seg0)
"
```

Expected: prints OK + segment count.

**Step 4: (Optional) End-to-end against a real consumer**

Run `meet-transcribe` or `vm-transcribe` pointing at the same audio, verify it completes without "audioscope produced no JSON output".

**Step 5: No commit** unless something needed fixing.

---

## Completion criteria

- [ ] 72+ tests green (65 pre-existing + 4 flat_to_legacy + 1 chunked integration + 2 short-path regression)
- [ ] Chunked mode writes `output-dir/audioscope_TS.json` in legacy dict schema
- [ ] Short mode behaviour byte-identical to before (same files, same names, same content)
- [ ] `meet-transcribe` and `vm-transcribe` can consume long-audio output without modification (verified via Task 4 offline smoke; optionally Task 6 real smoke)
- [ ] SKILL.md documents the new layout

## Out of scope (do not touch in this plan)

- `--debug` flag to suppress debug directory — user accepted keeping debug artifacts unconditionally
- Changing short-mode to flat schema — would break backward compat
- Changing stdout format — already identical in both modes via `format_diarize`
- Adding `--output-file` argument to pick custom filename — YAGNI; current TS-based naming is fine
- Sub-chunk resubmission for persistently-failing chunks (chunk 2 and 9 in 05-07 smoke) — belongs to Part 3

---

## For the executing agent — handoff notes

1. This plan is small: ~6 tasks, ~1 hour with tests. Execute as one batch.
2. The worktree is `/Users/iz/work/gski/.worktrees/audioscope-long-audio`. Branch is `feat/audioscope-long-audio`.
3. After Task 5 finishes, re-run full suite once more and use `finishing-a-development-branch` skill.
4. Do not modify any file outside `gski/` and `tests/` except `gski/skills/audioscope/SKILL.md`.
5. Consumer scripts live at `/Users/iz/work/scripts/meet-transcribe` and `/Users/iz/work/scripts/vm-transcribe` — they are documentation only; do NOT modify them.
