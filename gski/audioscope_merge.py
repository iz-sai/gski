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

    return merged


def _safe_parse(ts: str):
    try:
        return parse_ts(ts)
    except ValueError:
        return None
