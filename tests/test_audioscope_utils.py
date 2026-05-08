import subprocess
from unittest.mock import patch

import pytest

from gski.audioscope_utils import (
    probe_duration,
    parse_ts,
    format_ts,
    shift_ts,
    plan_chunks,
    ChunkSpec,
    extract_chunk_with_offset,
)


def test_probe_duration_parses_float():
    fake_run = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="7523.456\n", stderr=""
    )
    with patch("gski.audioscope_utils.subprocess.run", return_value=fake_run):
        assert probe_duration("x.ogg") == 7523.456


def test_probe_duration_raises_on_error():
    fake_run = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="not found"
    )
    with patch("gski.audioscope_utils.subprocess.run", return_value=fake_run):
        with pytest.raises(RuntimeError, match="ffprobe failed"):
            probe_duration("x.ogg")


@pytest.mark.parametrize("s,expected", [
    ("00:00", 0),
    ("0:05", 5),
    ("1:30", 90),
    ("01:30", 90),
    ("59:59", 3599),
    ("1:00:00", 3600),
    ("1:23:45", 5025),
    ("01:23:45", 5025),
])
def test_parse_ts(s, expected):
    assert parse_ts(s) == expected


def test_parse_ts_invalid():
    with pytest.raises(ValueError):
        parse_ts("garbage")
    with pytest.raises(ValueError):
        parse_ts("1:2:3:4")


@pytest.mark.parametrize("sec,expected", [
    (0, "00:00"),
    (5, "00:05"),
    (90, "01:30"),
    (3599, "59:59"),
    (3600, "1:00:00"),
    (5025, "1:23:45"),
])
def test_format_ts(sec, expected):
    assert format_ts(sec) == expected


def test_shift_ts():
    assert shift_ts("00:30", 60) == "01:30"
    assert shift_ts("05:00", 3600) == "1:05:00"


def test_plan_chunks_short_audio_one_chunk():
    chunks = plan_chunks(duration_sec=600, chunk_len_sec=900, overlap_sec=30)
    assert chunks == [ChunkSpec(index=0, start=0, end=600)]


def test_plan_chunks_exact_boundary():
    chunks = plan_chunks(duration_sec=1800, chunk_len_sec=900, overlap_sec=30)
    assert len(chunks) == 3
    assert chunks[0] == ChunkSpec(0, 0, 900)
    assert chunks[1] == ChunkSpec(1, 870, 1770)
    assert chunks[2] == ChunkSpec(2, 1740, 1800)


def test_plan_chunks_merges_tiny_tail():
    chunks = plan_chunks(duration_sec=910, chunk_len_sec=900, overlap_sec=30, min_chunk_sec=60)
    assert len(chunks) == 1
    assert chunks[0] == ChunkSpec(0, 0, 910)


def test_plan_chunks_2h():
    chunks = plan_chunks(duration_sec=7523, chunk_len_sec=900, overlap_sec=30)
    assert len(chunks) == 9
    assert chunks[0].start == 0
    assert chunks[-1].end == 7523
    for prev, curr in zip(chunks, chunks[1:]):
        assert prev.end - curr.start == 30


def test_extract_chunk_with_offset_shifts_start(tmp_path):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("gski.audioscope_utils.subprocess.run", side_effect=fake_run):
        extract_chunk_with_offset(
            "in.ogg", str(tmp_path / "out.ogg"),
            start=1000, end=1900, offset_sec=2,
        )
    assert len(calls) == 1
    cmd = calls[0]
    # start shifted to 1002, duration shrunk to 898
    assert "1002" in cmd
    assert "898" in cmd


def test_extract_chunk_with_offset_falls_back_when_offset_too_large(tmp_path):
    """If offset leaves <60s of chunk, fall back to regular extraction."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("gski.audioscope_utils.subprocess.run", side_effect=fake_run):
        # offset=100 leaves only 50s of a 150s chunk → fallback
        extract_chunk_with_offset(
            "in.ogg", str(tmp_path / "out.ogg"),
            start=0, end=150, offset_sec=100,
        )
    # fallback path should call ffmpeg with original start/end
    cmd = calls[0]
    assert "0" in cmd
    assert "150" in cmd
