from gski.audioscope_validators import (
    check_duration, check_loop, check_gaps, ValidationResult,
)


def seg(t, speaker="A", text="hello"):
    return {"s": speaker, "t": t, "x": text}


def test_duration_ok_when_last_ts_close_to_duration():
    segments = [seg("00:00"), seg("14:30")]
    r = check_duration(segments, chunk_duration_sec=900, threshold_sec=60)
    assert r.ok


def test_duration_fail_when_last_ts_too_far_from_duration():
    segments = [seg("00:00"), seg("05:00")]
    r = check_duration(segments, chunk_duration_sec=900, threshold_sec=60)
    assert not r.ok
    assert "truncat" in r.reason.lower() or "short" in r.reason.lower()


def test_duration_fail_on_empty():
    r = check_duration([], chunk_duration_sec=900, threshold_sec=60)
    assert not r.ok


def test_loop_detects_repeated_5gram():
    repeated = "the quick brown fox jumps over the lazy dog"
    segments = [seg("00:00", text=repeated)] * 10
    r = check_loop(segments, n=5, max_repeats=4)
    assert not r.ok
    assert "loop" in r.reason.lower() or "repeat" in r.reason.lower()


def test_loop_ok_on_normal_transcript():
    segments = [
        seg("00:00", text="hello everyone welcome to the meeting"),
        seg("00:10", text="today we will discuss the roadmap"),
        seg("00:25", text="first topic is the new feature rollout"),
    ]
    r = check_loop(segments, n=5, max_repeats=4)
    assert r.ok


def test_gap_ok_when_segments_dense():
    segments = [seg("00:00"), seg("00:30"), seg("01:00"), seg("02:30")]
    r = check_gaps(segments, max_gap_sec=180)
    assert r.ok


def test_gap_fail_on_large_silence():
    segments = [seg("00:00"), seg("05:00"), seg("14:00")]
    r = check_gaps(segments, max_gap_sec=180)
    assert not r.ok
    assert "gap" in r.reason.lower()
