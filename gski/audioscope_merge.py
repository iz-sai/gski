from difflib import SequenceMatcher

from gski.audioscope_utils import ChunkSpec, format_ts, parse_ts, shift_ts


DUP_SIMILARITY_THRESHOLD = 0.6
GAP_PLACEHOLDER_THRESHOLD_SEC = 180
SYSTEM_SPEAKER = "__system__"


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

    prev_chunks = [c for c, _ in chunk_results[:-1]]
    for prev_chunk, (chunk, segs) in zip(prev_chunks, chunk_results[1:]):
        shifted = _shift_segments(segs, chunk.start)
        overlap_start = chunk.start
        overlap_end = prev_chunk.end

        deduped = []
        for seg in shifted:
            try:
                ts_sec = parse_ts(seg.get("t", "00:00"))
            except ValueError:
                deduped.append(seg)
                continue
            if overlap_start <= ts_sec <= overlap_end:
                tail = [
                    m for m in merged
                    if m.get("t") and _safe_parse(m["t"]) is not None
                    and _safe_parse(m["t"]) >= overlap_start
                ]
                if any(_is_duplicate(seg, m) for m in tail):
                    continue
            deduped.append(seg)

        merged.extend(deduped)

    return _insert_gap_placeholders(merged)


def _insert_gap_placeholders(segments: list[dict]) -> list[dict]:
    if not segments:
        return segments
    out: list[dict] = []
    prev_sec: int | None = None
    for seg in segments:
        if seg.get("s") == SYSTEM_SPEAKER:
            out.append(seg)
            # don't update prev_sec based on system markers — they don't
            # represent real coverage
            continue
        cur_sec = _safe_parse(seg.get("t") or "")
        if prev_sec is not None and cur_sec is not None:
            diff = cur_sec - prev_sec
            if diff > GAP_PLACEHOLDER_THRESHOLD_SEC:
                mid = prev_sec + diff // 2
                mins = diff // 60
                secs = diff % 60
                out.append(
                    {
                        "s": SYSTEM_SPEAKER,
                        "t": format_ts(mid),
                        "x": f"[\u2026gap: {mins}m {secs}s untranscribed\u2026]",
                    }
                )
        out.append(seg)
        if cur_sec is not None:
            prev_sec = cur_sec
    return out


def _safe_parse(ts: str):
    try:
        return parse_ts(ts)
    except ValueError:
        return None
