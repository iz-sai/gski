import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .models import GEMINI_TEXT, GEMINI_TRANSCRIBE

MODELS = {k: GEMINI_TEXT[k] for k in ("flash", "pro")}

DEFAULT_LIKE = (
    "bizarre expressive non-verbal vocalizations: guttural growls, throat rumbles, "
    "exaggerated groans, theatrical gasps, comic grunts, lip smacking, gibberish noises"
)

PROMPT_SOUNDS = """Listen carefully to this audio and find non-verbal sounds that match this description:
{like}
{context}
Rules:
- Do NOT include normal words, speech, or dialogue.
- Do NOT include plain laughter or chuckles unless the description asks for them.
- Only report sounds that are clearly audible and distinct; return an empty list if there are none.
- Timestamps are relative to the start of this audio, format MM:SS.

Return a JSON array:
[{{"start": "MM:SS", "end": "MM:SS", "sound": "phonetic rendering of the sound", "description": "brief explanation", "slug": "short_snake_case_english_name"}}]
"""

genai = None
types = None


def _init_deps():
    global genai, types
    if genai is None:
        from google import genai as _genai
        from google.genai import types as _types

        genai = _genai
        types = _types


def _die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def _ffprobe_duration(path):
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ]
    )
    return float(out.decode().strip())


def _has_video(path):
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path),
        ]
    )
    return bool(out.strip())


def _make_chunks(src, tmp, chunk_secs):
    total = _ffprobe_duration(src)
    chunks = []
    start = 0.0
    i = 1
    while start < total:
        end = min(start + chunk_secs, total)
        out = Path(tmp) / f"part_{i}.mp3"
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-ss", str(start), "-to", str(end), "-i", str(src),
                "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(out), "-y",
            ],
            check=True,
        )
        chunks.append({"index": i, "path": out, "offset": start, "length": end - start})
        start = end
        i += 1
    return total, chunks


def _parse_offset(val):
    return float(str(val).rstrip("s")) if val else 0.0


def _parse_mmss(val):
    parts = [float(x) for x in str(val).strip().split(":")]
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs


def _fmt_ts(seconds):
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    base = f"{int(m):02d}:{s:04.1f}"
    return f"{int(h)}:{base}" if h else base


def _extract_words(interaction):
    words = []
    for step in getattr(interaction, "steps", []) or []:
        for content in getattr(step, "content", []) or []:
            for a in getattr(content, "annotations", []) or []:
                if getattr(a, "type", None) == "word_info":
                    words.append(
                        {
                            "text": getattr(a, "text", ""),
                            "speaker": getattr(a, "speaker", None) or "unknown",
                            "start": _parse_offset(getattr(a, "start_offset", None)),
                            "end": _parse_offset(getattr(a, "end_offset", None)),
                        }
                    )
    return words


def _clean_words(raw, chunk):
    out = []
    for w in raw:
        st, en = w["start"], w["end"]
        if en < st:
            en = st + 0.3
        if en - st > 5.0:
            en = st + 0.5
        if st > chunk["length"] + 2.0:
            continue
        en = min(chunk["length"], en)
        out.append(
            {
                "text": w["text"],
                "speaker": w["speaker"],
                "chunk": chunk["index"],
                "start": round(st + chunk["offset"], 2),
                "end": round(en + chunk["offset"], 2),
            }
        )
    out.sort(key=lambda w: w["start"])
    return out


def _group_segments(words, gap):
    segs = []
    cur = None
    for w in words:
        same = (
            cur
            and w["speaker"] == cur["speaker"]
            and w["chunk"] == cur["chunk"]
            and -0.2 <= w["start"] - cur["end"] <= gap
        )
        if same:
            cur["end"] = max(cur["end"], w["end"])
            cur["words"].append(w["text"])
        else:
            if cur:
                segs.append(cur)
            cur = {
                "speaker": w["speaker"],
                "chunk": w["chunk"],
                "start": w["start"],
                "end": w["end"],
                "words": [w["text"]],
            }
    if cur:
        segs.append(cur)
    return [
        {
            "speaker": s["speaker"],
            "chunk": s["chunk"],
            "start": s["start"],
            "end": s["end"],
            "duration": round(s["end"] - s["start"], 2),
            "text": " ".join(s["words"]).strip(),
        }
        for s in segs
    ]


def _transcription_config(args, diarize, timestamps):
    cfg = {}
    if args.lang:
        cfg["language_codes"] = [x.strip() for x in args.lang.split(",") if x.strip()]
    if args.smart:
        cfg["mode"] = "smart"
    else:
        mode = {"type": "verbatim"}
        if diarize:
            mode["diarization_mode"] = "speaker"
        if timestamps:
            mode["timestamp_granularities"] = ["word"]
        cfg["mode"] = mode
    return cfg


def _upload(client, path):
    return client.files.upload(file=str(path))


def _delete(client, f):
    try:
        client.files.delete(name=f.name)
    except Exception as e:
        _log(f"warning: could not delete {f.name}: {e}")


def _json_from_text(text):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1)
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _resolve_input(args):
    input_path = args.input or (args.audio[0] if getattr(args, "audio", None) else None)
    if not input_path:
        _die("FILE argument required (e.g. gski audioscope transcribe FILE)")
    src = Path(input_path)
    if not src.is_file():
        _die(f"input not found: {src}")
    if not os.environ.get("GEMINI_API_KEY"):
        _die("GEMINI_API_KEY env var required")
    for tool in ("ffmpeg", "ffprobe"):
        if subprocess.run(["which", tool], capture_output=True).returncode:
            _die(f"{tool} not found in PATH")
    out = Path(args.output_dir) / src.stem
    out.mkdir(parents=True, exist_ok=True)
    return src, out


def run_transcribe(args):
    diarize = not getattr(args, "no_diarize", False)
    timestamps = not getattr(args, "no_timestamps", False)
    if args.smart:
        diarize = timestamps = False
    src, out = _resolve_input(args)
    _init_deps()
    client = genai.Client()
    config = _transcription_config(args, diarize=diarize, timestamps=timestamps)

    t0 = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        total, chunks = _make_chunks(src, tmp, args.chunk)
        _log(f"progress: {src.name}: {total:.1f}s in {len(chunks)} chunk(s) (chunk={args.chunk:.0f}s)")

        words, texts = [], []
        for c in chunks:
            t_c = time.monotonic()
            _log(f"progress: chunk {c['index']}/{len(chunks)} ({c['offset']:.0f}s..{c['offset']+c['length']:.0f}s) uploading...")
            f = _upload(client, c["path"])
            try:
                c_words = []
                out_text = ""
                for attempt in range(1, 3):
                    _log(f"progress: chunk {c['index']}/{len(chunks)} transcribing via {GEMINI_TRANSCRIBE} (attempt {attempt})...")
                    interaction = client.interactions.create(
                        model=GEMINI_TRANSCRIBE,
                        input=[{"type": "audio", "uri": f.uri, "mime_type": f.mime_type}],
                        generation_config={"transcription_config": config},
                    )
                    cand_words = _clean_words(_extract_words(interaction), c)
                    cand_text = interaction.output_text or ""
                    if len(cand_words) > len(c_words):
                        c_words = cand_words
                        out_text = cand_text
                    if not timestamps or c["length"] < 180:
                        break
                    last_rel = (c_words[-1]["end"] - c["offset"]) if c_words else 0.0
                    if last_rel >= c["length"] * 0.75:
                        break
                    _log(
                        f"warning: chunk {c['index']} truncated at {last_rel:.0f}s/{c['length']:.0f}s "
                        f"({len(c_words)} words), retrying..."
                    )
            finally:
                _delete(client, f)
            texts.append(out_text)
            words.extend(c_words)
            dt_c = time.monotonic() - t_c
            _log(f"progress: chunk {c['index']}/{len(chunks)} done in {dt_c:.1f}s ({len(c_words)} words)")

    segments = _group_segments(words, args.gap) if words else []
    elapsed = round(time.monotonic() - t0, 2)
    result = {
        "source": src.name,
        "duration": round(total, 2),
        "elapsed_sec": elapsed,
        "chunk_secs": args.chunk,
        "model": GEMINI_TRANSCRIBE,
        "config": config,
        "segments": segments,
        "words": words,
        "text": "\n\n".join(t.strip() for t in texts if t.strip()),
    }
    (out / "transcript.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))

    if segments:
        lines = []
        for s in segments:
            spk = f" [chunk {s['chunk']}] {s['speaker']}" if diarize else ""
            lines.append(f"[{_fmt_ts(s['start'])}]{spk}: {s['text']}")
        txt = "\n".join(lines)
    else:
        txt = result["text"]
    (out / "transcript.txt").write_text(txt)
    print(txt)
    _log(f"\nsaved: {out / 'transcript.json'}, {out / 'transcript.txt'} (in {elapsed:.1f}s)")


def _detect_sounds(client, model, chunk, prompt):
    f = _upload(client, chunk["path"])
    try:
        resp = client.models.generate_content(
            model=model,
            contents=[f, prompt],
            config=types.GenerateContentConfig(
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
            ),
        )
    finally:
        _delete(client, f)
    found = []
    for s in _json_from_text(resp.text):
        try:
            st = _parse_mmss(s["start"])
            en = _parse_mmss(s["end"])
        except (KeyError, ValueError):
            continue
        if not 0 <= st < en <= chunk["length"] + 1.0:
            continue
        found.append(
            {
                "start": round(st + chunk["offset"], 1),
                "end": round(en + chunk["offset"], 1),
                "sound": s.get("sound", ""),
                "description": s.get("description", ""),
                "slug": s.get("slug", "sound"),
            }
        )
    return found


def _slug(s):
    s = re.sub(r"[^a-z0-9_]+", "", str(s).lower().replace(" ", "_")).strip("_")
    return s or "sound"


def _cut(src, dest_dir, items, total, pad, with_video):
    for i, it in enumerate(items, 1):
        name = f"sample_{i:02d}_{_slug(it['slug'])}"
        start = max(0.0, it["start"] - pad)
        end = min(total, it["end"] + pad)
        dur = round(end - start, 2)
        base = ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", str(src)]
        mp3 = dest_dir / f"{name}.mp3"
        subprocess.run(base + ["-vn", "-b:a", "192k", str(mp3), "-y"], check=True)
        it["id"] = name
        it["cut_start"] = round(start, 2)
        it["cut_end"] = round(end, 2)
        it["audio"] = str(mp3)
        if with_video:
            mp4 = dest_dir / f"{name}.mp4"
            subprocess.run(
                base + ["-c:v", "libx264", "-c:a", "aac", "-crf", "22", str(mp4), "-y"],
                check=True,
            )
            it["video"] = str(mp4)


def run_sounds(args):
    src, out = _resolve_input(args)
    _init_deps()
    client = genai.Client()
    model = MODELS[args.model]
    context = f"Context: {args.context}\n" if args.context else ""
    prompt = PROMPT_SOUNDS.format(like=args.like, context=context)

    with tempfile.TemporaryDirectory() as tmp:
        total, chunks = _make_chunks(src, tmp, args.chunk)
        _log(f"{src.name}: {total:.1f}s in {len(chunks)} chunk(s)")
        found = []
        for c in chunks:
            _log(f"chunk {c['index']}/{len(chunks)}: scanning")
            found.extend(_detect_sounds(client, model, c, prompt))

    picked = sorted(found, key=lambda x: x["start"])
    for it in picked:
        it["start_ts"] = _fmt_ts(it["start"])
        it["end_ts"] = _fmt_ts(it["end"])

    if args.extract and picked:
        sdir = out / "sounds"
        sdir.mkdir(exist_ok=True)
        _cut(src, sdir, picked, total, args.pad, _has_video(src))

    result = {
        "source": src.name,
        "duration": round(total, 2),
        "like": args.like,
        "sounds": picked,
    }
    (out / "sounds.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))

    if not picked:
        print("no matching sounds found")
    for it in picked:
        print(f"[{it['start_ts']} - {it['end_ts']}] {it['sound']} - {it['description']}")
        if "audio" in it:
            print(f"    {it['audio']}" + (f"  {it['video']}" if "video" in it else ""))
    _log(f"\nsaved: {out / 'sounds.json'}")
