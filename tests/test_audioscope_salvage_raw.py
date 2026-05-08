import json

from gski.audioscope_salvage import salvage_raw_text


def test_salvage_raw_text_closes_whitespace_truncated_json():
    """MAX_TOKENS on whitespace after a valid segment. Salvage must truncate
    at the last complete `}` and append `]`."""
    valid = '[{"s":"A","t":"00:00","x":"hello"},{"s":"B","t":"00:05","x":"world"}'
    broken = valid + " " * 5000
    cleaned, was_salvaged = salvage_raw_text(broken)
    assert was_salvaged is True
    segs = json.loads(cleaned)
    assert len(segs) == 2
    assert segs[-1]["x"] == "world"


def test_salvage_raw_text_passthrough_on_valid_json():
    valid = '[{"s":"A","t":"00:00","x":"hi"}]'
    cleaned, was = salvage_raw_text(valid)
    assert was is False
    assert cleaned == valid


def test_salvage_raw_text_detects_character_loop_inside_segment():
    """MAX_TOKENS on a single char inside an x-field before the closing quote.
    Salvage must cut back to the last complete segment."""
    broken = (
        '[{"s":"A","t":"00:00","x":"hello"},'
        '{"s":"B","t":"00:05","x":"aaaa'
        + "a" * 5000
    )
    cleaned, was = salvage_raw_text(broken)
    assert was is True
    segs = json.loads(cleaned)
    assert len(segs) == 1
    assert segs[0]["x"] == "hello"


def test_salvage_raw_text_untouched_when_json_broken_for_other_reasons():
    """If JSON is broken but no whitespace/char loop signature is present,
    don't touch it — let the caller raise a normal parse error."""
    broken = '{"invalid": but no array'
    cleaned, was = salvage_raw_text(broken)
    assert was is False
    assert cleaned == broken


def test_salvage_raw_text_handles_trailing_comma():
    """Truncation right after a comma; the last `}` is still the segment
    boundary we want to cut at."""
    broken = (
        '[{"s":"A","t":"00:00","x":"hello"},'
        '{"s":"B","t":"00:05","x":"world"},'
        + " " * 2000
    )
    cleaned, was = salvage_raw_text(broken)
    assert was is True
    segs = json.loads(cleaned)
    assert len(segs) == 2
