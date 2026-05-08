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
    assert [s["x"] for s in merged] == ["alpha", "omega", "beta", "gamma"]
    assert [s["t"] for s in merged] == ["00:10", "14:30", "15:10", "28:30"]


def test_merge_drops_duplicate_in_overlap():
    c0 = ChunkSpec(0, 0, 900)
    c1 = ChunkSpec(1, 870, 1800)
    r0 = [seg("00:10", "alpha"), seg("14:35", "see you tomorrow everyone")]
    r1 = [seg("00:05", "see you tomorrow everyone"), seg("02:00", "new content")]
    merged = merge_chunks([(c0, r0), (c1, r1)])
    texts = [s["x"] for s in merged]
    assert texts.count("see you tomorrow everyone") == 1
    assert "new content" in texts


def test_merge_keeps_distinct_utterances_in_overlap():
    c0 = ChunkSpec(0, 0, 900)
    c1 = ChunkSpec(1, 870, 1800)
    r0 = [seg("14:50", "that wraps up the quarterly review")]
    r1 = [seg("00:05", "let's move on to product roadmap planning")]
    merged = merge_chunks([(c0, r0), (c1, r1)])
    assert len(merged) == 2
