from gski.audioscope_merge import merge_chunks
from gski.audioscope_utils import ChunkSpec


def seg(t, x, s="A"):
    return {"s": s, "t": t, "x": x}


def test_merge_no_overlap_shifts_timestamps():
    c0 = ChunkSpec(0, 0, 900)
    c1 = ChunkSpec(1, 870, 1800)
    r0 = [seg("00:10", "alpha"), seg("14:30", "omega")]
    r1 = [seg("00:40", "beta"), seg("14:00", "gamma")]
    merged = merge_chunks([(c0, r0), (c1, r1)])
    # chunk1 starts at 870s: 00:40 -> 910s -> "15:10"; 14:00 -> 1710s -> "28:30"
    # Gap placeholders are inserted between wide-spaced segments.
    real = [s for s in merged if s["s"] != "__system__"]
    assert [s["x"] for s in real] == ["alpha", "omega", "beta", "gamma"]
    assert [s["t"] for s in real] == ["00:10", "14:30", "15:10", "28:30"]


def test_merge_drops_duplicate_in_overlap():
    c0 = ChunkSpec(0, 0, 900)
    c1 = ChunkSpec(1, 870, 1800)
    r0 = [seg("00:10", "alpha"), seg("14:35", "see you tomorrow everyone")]
    r1 = [seg("00:05", "see you tomorrow everyone"), seg("02:00", "new content")]
    merged = merge_chunks([(c0, r0), (c1, r1)])
    real_texts = [s["x"] for s in merged if s["s"] != "__system__"]
    assert real_texts.count("see you tomorrow everyone") == 1
    assert "new content" in real_texts


def test_merge_keeps_distinct_utterances_in_overlap():
    c0 = ChunkSpec(0, 0, 900)
    c1 = ChunkSpec(1, 870, 1800)
    r0 = [seg("14:50", "that wraps up the quarterly review")]
    r1 = [seg("00:05", "let's move on to product roadmap planning")]
    merged = merge_chunks([(c0, r0), (c1, r1)])
    real = [s for s in merged if s["s"] != "__system__"]
    assert len(real) == 2


def test_merge_inserts_gap_placeholder_when_adjacent_segs_have_big_time_diff():
    c0 = ChunkSpec(index=0, start=0, end=900)
    segs0 = [
        {"s": "A", "t": "00:00", "x": "hello"},
        {"s": "A", "t": "01:00", "x": "first minute"},
        # gap from 01:00 to 08:00 = 420s >180s threshold
        {"s": "A", "t": "08:00", "x": "jump ahead"},
    ]
    merged = merge_chunks([(c0, segs0)])
    texts = [s["x"] for s in merged]
    assert any("gap" in t.lower() and "untranscribed" in t.lower() for t in texts)
    # placeholder timestamp inside the gap
    for s in merged:
        if "gap" in s["x"].lower() and "untranscribed" in s["x"].lower():
            assert s["s"] == "__system__"
            # must be between 01:00 (60s) and 08:00 (480s)
            from gski.audioscope_utils import parse_ts
            t_sec = parse_ts(s["t"])
            assert 60 < t_sec < 480
            break


def test_merge_no_placeholder_for_small_gap():
    c0 = ChunkSpec(index=0, start=0, end=900)
    segs0 = [
        {"s": "A", "t": "00:00", "x": "a"},
        {"s": "A", "t": "01:30", "x": "b"},  # 90s gap, OK
    ]
    merged = merge_chunks([(c0, segs0)])
    assert all("gap" not in s["x"].lower() for s in merged)


def test_merge_inserts_gap_placeholder_across_chunk_boundary():
    """Gap that spans a chunk boundary (e.g. last seg of c0 at 14:00, first seg
    of c1 at 08:00 which shifts to 14:30+08:00=22:30) should also be detected."""
    c0 = ChunkSpec(index=0, start=0, end=900)
    c1 = ChunkSpec(index=1, start=870, end=1800)
    r0 = [{"s": "A", "t": "10:00", "x": "earlier"}]  # 10:00 = 600s
    r1 = [{"s": "A", "t": "08:00", "x": "later"}]  # shifts to 870+480=1350s = 22:30
    merged = merge_chunks([(c0, r0), (c1, r1)])
    # gap 600 → 1350 = 750s > 180s
    texts = [s["x"] for s in merged]
    assert any("gap" in t.lower() and "untranscribed" in t.lower() for t in texts)
