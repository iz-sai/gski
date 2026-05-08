import subprocess
from unittest.mock import patch

import pytest

from gski.audioscope_utils import probe_duration


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
