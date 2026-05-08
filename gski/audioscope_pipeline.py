import json
from datetime import datetime
from pathlib import Path

from gski.audioscope_utils import (
    probe_duration,
    plan_chunks,
    extract_chunk,
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
from gski.audioscope_merge import merge_chunks


RETRY_CONFIGS = [
    {"seed": 42, "temperature": 0.0},
    {"seed": 43, "temperature": 0.0},
    {"seed": 44, "temperature": 0.1},
]

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


def _transcribe_single_chunk_with_retries(
    client,
    *,
    model,
    chunk_path,
    chunk,
    total_chunks,
    prev_tail,
    diarize,
    timestamps,
):
    attempts = []
    best_segments: list[dict] = []

    for attempt_idx, overrides in enumerate(RETRY_CONFIGS):
        prompt = build_prompt_for_chunk(
            chunk_index=chunk.index,
            total_chunks=total_chunks,
            chunk_start_sec=chunk.start,
            chunk_duration_sec=chunk.duration,
            diarize=diarize,
            timestamps=timestamps,
            prev_tail=prev_tail,
        )
        config = None
        if diarize:
            config = build_diarize_config(
                timestamps=timestamps,
                seed=overrides["seed"],
                temperature=overrides["temperature"],
            )

        try:
            uploaded = client.files.upload(file=chunk_path)
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
                    "overrides": overrides,
                }
            )
            continue

        failed_check, reason = _validate_chunk(segments, chunk.duration)
        ok = failed_check is None
        attempts.append(
            {
                "attempt": attempt_idx,
                "ok": ok,
                "failed_check": failed_check,
                "reason": reason,
                "meta": meta,
                "segment_count": len(segments),
                "overrides": overrides,
            }
        )
        if ok:
            return segments, attempts
        # Only keep as fallback if NOT contaminated by a repetition loop.
        # Duration/gap failures may still yield usable partial content; loops
        # are toxic (they corrupt downstream merge and reading experience).
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
