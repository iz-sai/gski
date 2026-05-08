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
        return ValidationResult(True)

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
