import json
from datetime import datetime
from pathlib import Path

from gski.audioscope_utils import (
    probe_duration,
    plan_chunks,
    extract_chunk,
    extract_chunk_with_offset,
)
from gski.audioscope_gemini import (
    build_diarize_config,
    build_prompt_for_chunk,
    transcribe_chunk,
    ChunkTranscriptionError,
)
from gski.audioscope_validators import (
    check_duration,
    check_loop,
    check_gaps,
)
from gski.audioscope_salvage import salvage_segments
from gski.audioscope_merge import merge_chunks


_ANTI_LOOP_PROMPT_SUFFIX = (
    "CRITICAL: if you cannot transcribe a portion of the audio (silence, noise, "
    "unclear speech), output a single segment with x=\"[unclear]\" and continue. "
    "DO NOT repeat any word or phrase more than 3 times in a single segment. "
    "DO NOT skip audio — every minute must have at least one segment."
)

# Retry strategies. Attempt 0 is the default hardened config; attempts 1-2
# perturb the actual inputs (audio bytes or prompt) rather than only the seed,
# because empirically Gemini produces near-identical output across seeds 42/43/44
# when the failure is content-driven (silence region, specific phonetic trigger).
RETRY_STRATEGIES = [
    {"kind": "default", "seed": 42, "temperature": 0.0},
    {
        "kind": "audio_offset",
        "seed": 42,
        "temperature": 0.0,
        "offset_sec": 2,
    },
    {
        "kind": "prompt_variant",
        "seed": 99,
        "temperature": 0.2,
        "prompt_suffix": _ANTI_LOOP_PROMPT_SUFFIX,
    },
]

# Kept for backward compat / reference; not used anymore.
RETRY_CONFIGS = RETRY_STRATEGIES

TAIL_SEGMENTS_FOR_CONTEXT = 5


def _validate_chunk(segments, chunk_duration_sec):
    for name, result in [
        ("duration", check_duration(segments, chunk_duration_sec)),
        ("loop", check_loop(segments)),
        ("gaps", check_gaps(segments)),
    ]:
        if not result.ok:
            return name, result.reason
    return None, None


def _apply_strategy(
    strategy: dict, *, chunk, audio_path: str, tmp_dir: Path, chunk_path: str,
) -> tuple[str, str | None]:
    """Prepare audio file + prompt extra for a given retry strategy.

    Returns (chunk_path_to_upload, prompt_extra_or_None).
    """
    kind = strategy["kind"]
    if kind == "default":
        return chunk_path, None
    if kind == "audio_offset":
        off_path = str(tmp_dir / f"chunk_{chunk.index:03d}.off.ogg")
        extract_chunk_with_offset(
            audio_path, off_path,
            start=chunk.start, end=chunk.end,
            offset_sec=strategy["offset_sec"],
        )
        return off_path, None
    if kind == "prompt_variant":
        return chunk_path, strategy["prompt_suffix"]
    raise ValueError(f"unknown retry strategy: {kind}")


def _transcribe_single_chunk_with_retries(
    client,
    *,
    model,
    audio_path: str,
    tmp_dir: Path,
    chunk_path,
    chunk,
    total_chunks,
    prev_tail,
    diarize,
    timestamps,
):
    attempts = []
    best_segments: list[dict] = []

    for attempt_idx, strategy in enumerate(RETRY_STRATEGIES):
        # Prepare audio + prompt extra according to the strategy.
        try:
            upload_path, prompt_extra = _apply_strategy(
                strategy,
                chunk=chunk,
                audio_path=audio_path,
                tmp_dir=Path(tmp_dir),
                chunk_path=chunk_path,
            )
        except Exception as e:
            attempts.append(
                {
                    "attempt": attempt_idx,
                    "ok": False,
                    "error": f"strategy setup failed: {e}",
                    "strategy": strategy,
                }
            )
            continue

        prompt = build_prompt_for_chunk(
            chunk_index=chunk.index,
            total_chunks=total_chunks,
            chunk_start_sec=chunk.start,
            chunk_duration_sec=chunk.duration,
            diarize=diarize,
            timestamps=timestamps,
            prev_tail=prev_tail,
            extra_instruction=prompt_extra,
        )
        config = None
        if diarize:
            config = build_diarize_config(
                timestamps=timestamps,
                seed=strategy["seed"],
                temperature=strategy["temperature"],
            )

        try:
            uploaded = client.files.upload(file=upload_path)
            segments, meta = transcribe_chunk(
                client,
                model=model,
                audio_part=uploaded,
                config=config,
                prompt=prompt,
            )
        except ChunkTranscriptionError as e:
            attempts.append(
                {
                    "attempt": attempt_idx,
                    "ok": False,
                    "error": str(e),
                    "meta": e.meta,
                    "strategy": strategy,
                }
            )
            continue

        # If strategy was audio_offset, the model saw audio starting at
        # chunk.start+offset — shift timestamps back so they remain relative
        # to chunk.start (what the merge step expects).
        if strategy["kind"] == "audio_offset":
            offset = strategy["offset_sec"]
            shifted = []
            for seg in segments:
                new = dict(seg)
                t = seg.get("t")
                if t:
                    try:
                        from gski.audioscope_utils import parse_ts, format_ts
                        new["t"] = format_ts(parse_ts(t) + offset)
                    except ValueError:
                        pass
                shifted.append(new)
            segments = shifted

        # Cut intra-segment repetition loops before validation.
        segments, salvaged = salvage_segments(segments)

        failed_check, reason = _validate_chunk(segments, chunk.duration)
        ok = failed_check is None
        attempts.append(
            {
                "attempt": attempt_idx,
                "ok": ok,
                "failed_check": failed_check,
                "reason": reason,
                "salvaged": salvaged,
                "meta": meta,
                "segment_count": len(segments),
                "strategy": strategy,
            }
        )
        if ok:
            return segments, attempts
        if salvaged and check_loop(segments).ok:
            return segments, attempts
        if check_loop(segments).ok and len(segments) > len(best_segments):
            best_segments = segments

    return best_segments, attempts


def transcribe_long(
    client,
    *,
    audio_path: str,
    model: str,
    diarize: bool,
    timestamps: bool,
    tmp_dir,
    output_dir,
    chunk_len_sec: int = 900,
    overlap_sec: int = 30,
):
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / f"audioscope_{run_ts}"
    run_dir.mkdir(exist_ok=True)

    duration = probe_duration(audio_path)
    chunks = plan_chunks(duration, chunk_len_sec, overlap_sec)

    warnings: list[str] = []
    chunks_meta: list[dict] = []
    chunk_results: list = []
    prev_tail = None

    for chunk in chunks:
        if len(chunks) == 1:
            chunk_path = str(audio_path)
        else:
            chunk_path = str(tmp_dir / f"chunk_{chunk.index:03d}.ogg")
            extract_chunk(audio_path, chunk_path, chunk.start, chunk.end)

        segments, attempts = _transcribe_single_chunk_with_retries(
            client,
            model=model,
            audio_path=audio_path,
            tmp_dir=tmp_dir,
            chunk_path=chunk_path,
            chunk=chunk,
            total_chunks=len(chunks),
            prev_tail=prev_tail,
            diarize=diarize,
            timestamps=timestamps,
        )

        chunk_record = {
            "chunk": {"index": chunk.index, "start": chunk.start, "end": chunk.end},
            "attempts": attempts,
        }
        (run_dir / f"chunk_{chunk.index:03d}.meta.json").write_text(
            json.dumps(chunk_record, indent=2, ensure_ascii=False, default=str)
        )
        if attempts and isinstance(attempts[-1].get("meta"), dict):
            raw = attempts[-1]["meta"].get("raw_text", "")
            if raw:
                (run_dir / f"chunk_{chunk.index:03d}.raw.txt").write_text(raw)

        chunks_meta.append(chunk_record)
        if not segments:
            warnings.append(
                f"chunk {chunk.index} ({chunk.start}..{chunk.end}s) produced no valid segments"
            )
        elif not any(a.get("ok") for a in attempts):
            warnings.append(
                f"chunk {chunk.index} ({chunk.start}..{chunk.end}s) accepted with validation failures"
            )
        chunk_results.append((chunk, segments))
        if segments:
            prev_tail = segments[-TAIL_SEGMENTS_FOR_CONTEXT:]

    merged = merge_chunks(chunk_results)

    (run_dir / "merged.json").write_text(
        json.dumps(merged, indent=2, ensure_ascii=False)
    )

    return {
        "segments": merged,
        "chunks_meta": chunks_meta,
        "warnings": warnings,
        "run_dir": str(run_dir),
        "duration_sec": duration,
        "num_chunks": len(chunks),
    }
