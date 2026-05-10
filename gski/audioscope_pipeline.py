import json
from datetime import datetime
from pathlib import Path

from gski.audioscope_utils import (
    probe_duration,
    plan_chunks,
    extract_chunk,
    extract_chunk_with_offset,
    format_ts,
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


def _chunk_is_unhealthy(record: dict) -> bool:
    """A chunk is unhealthy if its final retry attempt failed validation
    (accepted with failures) or no attempts succeeded at all. Used to
    drive the salvage pass."""
    attempts = record.get("attempts", [])
    if not attempts:
        return True
    return not any(a.get("ok") for a in attempts)


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


def salvage_chunk_with_pro(
    client,
    chunk,
    *,
    model: str,
    audio_path: str,
    tmp_dir,
    chunk_path: str,
    total_chunks: int,
    prev_tail,
    diarize: bool,
    timestamps: bool,
):
    """Retry a single failing chunk on the salvage model (typically pro).
    Reuses the full diverse-retry ladder. Returns (segments, attempts).
    Segments may be empty if even pro fails."""
    return _transcribe_single_chunk_with_retries(
        client,
        model=model,
        audio_path=audio_path,
        tmp_dir=Path(tmp_dir),
        chunk_path=chunk_path,
        chunk=chunk,
        total_chunks=total_chunks,
        prev_tail=prev_tail,
        diarize=diarize,
        timestamps=timestamps,
    )


def salvage_chunk_with_subchunks(
    client,
    chunk,
    *,
    audio_path: str,
    model: str,
    diarize: bool,
    timestamps: bool,
    tmp_dir,
    subchunk_sec: int = 180,
):
    """Split a failed chunk into fixed-length sub-chunks (no overlap),
    transcribe each on the given model, stitch results into the parent
    chunk's local time frame (relative to chunk.start).
    Returns (segments_shifted, attempts_summary_list)."""
    from gski.audioscope_utils import ChunkSpec, parse_ts, format_ts

    tmp_dir = Path(tmp_dir)
    all_segments: list[dict] = []
    all_attempts: list[dict] = []

    offset_in_parent = 0
    sub_idx = 0
    while offset_in_parent < chunk.duration:
        sub_len = min(subchunk_sec, chunk.duration - offset_in_parent)
        sub_start = chunk.start + offset_in_parent
        sub_end = sub_start + sub_len
        sub_path = tmp_dir / f"subchunk_{chunk.index:03d}_{sub_idx:03d}.ogg"
        # Extract from the original audio file.
        extract_chunk(audio_path, str(sub_path), sub_start, sub_end)
        # Distinct index space for sub-chunks so debug artefacts don't collide.
        sub_spec = ChunkSpec(
            index=1000 * (chunk.index + 1) + sub_idx,
            start=sub_start,
            end=sub_end,
        )
        sub_segments, sub_attempts = _transcribe_single_chunk_with_retries(
            client,
            model=model,
            audio_path=audio_path,
            tmp_dir=tmp_dir,
            chunk_path=str(sub_path),
            chunk=sub_spec,
            total_chunks=1,
            prev_tail=None,
            diarize=diarize,
            timestamps=timestamps,
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
    salvage: bool = False,
    salvage_model: str = "gemini-3-pro-preview",
    salvage_subchunk_sec: int = 180,
    salvage_max_depth: int = 2,
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
                f"chunk {chunk.index} ({chunk.start}..{chunk.end}s) produced no valid segments; inserted lost-chunk placeholder"
            )
            segments = [
                {
                    "s": "__system__",
                    "t": format_ts(chunk.start),
                    "x": f"[\u2026chunk lost: {chunk.start}s\u2013{chunk.end}s, all retries failed\u2026]",
                }
            ]
        elif not any(a.get("ok") for a in attempts):
            warnings.append(
                f"chunk {chunk.index} ({chunk.start}..{chunk.end}s) accepted with validation failures"
            )
        chunk_results.append((chunk, segments))
        if segments:
            # Only carry over real segments for context, skip system markers.
            real = [s for s in segments if s.get("s") != "__system__"]
            prev_tail = real[-TAIL_SEGMENTS_FOR_CONTEXT:] if real else prev_tail

    if salvage:
        for i, record in enumerate(chunks_meta):
            if not _chunk_is_unhealthy(record):
                continue
            chunk, _orig_segments = chunk_results[i]
            ladder_results: dict = {}

            # Step 1: pro fallback on the full chunk.
            if salvage_max_depth >= 1:
                if len(chunks) == 1:
                    sc_path = str(audio_path)
                else:
                    sc_path = str(tmp_dir / f"chunk_{chunk.index:03d}.ogg")
                pro_segs, pro_attempts = salvage_chunk_with_pro(
                    client, chunk,
                    model=salvage_model,
                    audio_path=audio_path,
                    tmp_dir=tmp_dir,
                    chunk_path=sc_path,
                    total_chunks=len(chunks),
                    prev_tail=None,
                    diarize=diarize, timestamps=timestamps,
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

            # Step 2: sub-chunk with flash.
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

            # Step 3: sub-chunk with pro.
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
                f"chunk {chunk.index} salvage FAILED "
                f"(depth={salvage_max_depth}); leaving as-is"
            )

        # Re-write updated meta files after salvage.
        for record in chunks_meta:
            idx = record["chunk"]["index"]
            (run_dir / f"chunk_{idx:03d}.meta.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=False, default=str)
            )

    merged = merge_chunks(chunk_results)

    (run_dir / "merged.json").write_text(
        json.dumps(merged, indent=2, ensure_ascii=False)
    )

    coverage = summarize_coverage(merged)
    if coverage["total_untranscribed_sec"] > 0:
        parts = []
        if coverage["gap_count"]:
            g = coverage["gap_seconds"]
            parts.append(f"{coverage['gap_count']} gap(s) totalling {g // 60}m {g % 60}s")
        if coverage["lost_chunk_count"]:
            l = coverage["lost_chunk_seconds"]
            parts.append(f"{coverage['lost_chunk_count']} lost chunk(s) totalling {l // 60}m {l % 60}s")
        warnings.append(
            "coverage: " + ", ".join(parts)
            + " untranscribed (see segments with speaker \"__system__\")"
        )

    return {
        "segments": merged,
        "chunks_meta": chunks_meta,
        "warnings": warnings,
        "run_dir": str(run_dir),
        "duration_sec": duration,
        "num_chunks": len(chunks),
        "coverage": coverage,
    }


def summarize_coverage(segments: list[dict]) -> dict:
    import re
    gap_count = 0
    gap_seconds = 0
    lost_count = 0
    lost_seconds = 0
    gap_re = re.compile(r"gap:\s*(\d+)m\s*(\d+)s")
    lost_re = re.compile(r"chunk lost:\s*(\d+)s\s*[\u2013-]\s*(\d+)s")
    for seg in segments:
        if seg.get("s") != "__system__":
            continue
        text = seg.get("x", "")
        m = gap_re.search(text)
        if m:
            gap_count += 1
            gap_seconds += int(m.group(1)) * 60 + int(m.group(2))
            continue
        m = lost_re.search(text)
        if m:
            lost_count += 1
            lost_seconds += int(m.group(2)) - int(m.group(1))
    return {
        "gap_count": gap_count,
        "lost_chunk_count": lost_count,
        "gap_seconds": gap_seconds,
        "lost_chunk_seconds": lost_seconds,
        "total_untranscribed_sec": gap_seconds + lost_seconds,
    }


def flat_segments_to_legacy_dict(segments: list[dict]) -> dict:
    out = []
    for seg in segments:
        out.append({
            "speaker": seg.get("s", ""),
            "timestamp": seg.get("t", ""),
            "content": seg.get("x", ""),
        })
    return {"summary": "", "segments": out}
