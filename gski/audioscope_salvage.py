import re
from collections import Counter

LOOP_PLACEHOLDER = "[…cut: repetition loop…]"

_WORD_RE = re.compile(r"\w+", re.UNICODE)

# Intra-segment loop thresholds. Tuned so that:
#   - stutters ("да да да да") with <10 repeats pass through
#   - real Gemini MAX_TOKENS loops ('на на na na ...' x100+) are cut
_LOOP_MIN_TOKENS = 30       # segments shorter than this are not scanned
_LOOP_NGRAM = 1             # 1-gram is enough for word-loops; 5-gram catches phrase loops
_LOOP_MAX_REPEATS = 20      # a single token repeated >20x in one segment = loop
_PHRASE_NGRAM = 5
_PHRASE_MAX_REPEATS = 8


def _find_loop_start(text: str) -> int | None:
    """Return character offset where a repetition loop begins, or None."""
    tokens = list(_WORD_RE.finditer(text.lower()))
    if len(tokens) < _LOOP_MIN_TOKENS:
        return None

    # Word-level loop: scan for any token repeated >_LOOP_MAX_REPEATS times
    # in a row (allowing punctuation/whitespace between).
    counts = Counter(m.group() for m in tokens)
    top, top_count = counts.most_common(1)[0]
    if top_count > _LOOP_MAX_REPEATS:
        # Find first position where this token starts a long run.
        run = 0
        run_start_char = None
        for m in tokens:
            if m.group() == top:
                if run == 0:
                    run_start_char = m.start()
                run += 1
                if run > _LOOP_MAX_REPEATS:
                    return run_start_char
            else:
                # Allow short gaps (punctuation/spaces only between repeats).
                between = text[tokens[tokens.index(m) - 1].end(): m.start()] if run else ""
                if run and re.fullmatch(r"[\s\W]*", between, re.UNICODE):
                    # still within the run — but token differs, so reset
                    pass
                run = 0
                run_start_char = None

    # Phrase-level loop: n-gram repeated >_PHRASE_MAX_REPEATS times.
    words = [m.group() for m in tokens]
    if len(words) >= _PHRASE_NGRAM * (_PHRASE_MAX_REPEATS + 1):
        shingles = [tuple(words[i:i + _PHRASE_NGRAM]) for i in range(len(words) - _PHRASE_NGRAM + 1)]
        sh_counts = Counter(shingles)
        top_sh, top_sh_count = sh_counts.most_common(1)[0]
        if top_sh_count > _PHRASE_MAX_REPEATS:
            # Find first occurrence of this shingle in the token stream.
            for i in range(len(words) - _PHRASE_NGRAM + 1):
                if tuple(words[i:i + _PHRASE_NGRAM]) == top_sh:
                    return tokens[i].start()

    return None


def _salvage_one(text: str) -> tuple[str, bool]:
    loop_start = _find_loop_start(text)
    if loop_start is None:
        return text, False
    prefix = text[:loop_start].rstrip(" ,.-—…\t\n")
    if not prefix:
        return LOOP_PLACEHOLDER, True
    return f"{prefix} {LOOP_PLACEHOLDER}", True


def salvage_segments(segments: list[dict]) -> tuple[list[dict], bool]:
    modified = False
    out = []
    for seg in segments:
        text = seg.get("x") or ""
        cleaned, was_cut = _salvage_one(text)
        if was_cut:
            modified = True
            out.append({**seg, "x": cleaned})
        else:
            out.append(seg)
    return out, modified
