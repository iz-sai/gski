import re
from dataclasses import dataclass
from collections import Counter

from gski.audioscope_utils import parse_ts


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str | None = None


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def est_speech_sec(text: str | None, words_per_sec: float = 2.5) -> int:
    if not text:
        return 0
    return int(len(_WORD_RE.findall(text)) / words_per_sec)


def _last_ts_and_text(segments) -> tuple[int | None, str]:
    for seg in reversed(segments):
        if seg.get("t"):
            try:
                return parse_ts(seg["t"]), seg.get("x") or ""
            except ValueError:
                continue
    return None, ""


def check_duration(segments, chunk_duration_sec: int, threshold_sec: int = 60) -> ValidationResult:
    if not segments:
        return ValidationResult(False, "empty transcript")
    last, last_text = _last_ts_and_text(segments)
    if last is None:
        return ValidationResult(False, "no parseable timestamps")
    est_end = last + est_speech_sec(last_text)
    delta = chunk_duration_sec - est_end
    if delta > threshold_sec:
        return ValidationResult(
            False,
            f"transcript likely truncated: last_ts={last}s (est_end={est_end}s), chunk={chunk_duration_sec}s (delta={delta}s)"
        )
    if last - chunk_duration_sec > threshold_sec:
        return ValidationResult(
            False,
            f"last_ts {last}s exceeds chunk duration {chunk_duration_sec}s (likely loop)"
        )
    return ValidationResult(True)


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
    prev_end = None
    for seg in segments:
        if not seg.get("t"):
            continue
        try:
            cur = parse_ts(seg["t"])
        except ValueError:
            continue
        if prev_end is not None and cur - prev_end > max_gap_sec:
            return ValidationResult(
                False,
                f"coverage gap {cur - prev_end}s at {seg['t']} (threshold {max_gap_sec}s)"
            )
        prev_end = cur + est_speech_sec(seg.get("x"))
    return ValidationResult(True)
