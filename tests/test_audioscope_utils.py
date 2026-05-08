import subprocess
from unittest.mock import patch

import pytest

from gski.audioscope_utils import probe_duration, parse_ts, format_ts, shift_ts


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
