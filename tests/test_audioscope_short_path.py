import json
import types
from unittest.mock import MagicMock, patch

from gski import audioscope as cli


def test_cli_short_diarize_writes_flat_json_and_raw(tmp_path, monkeypatch):
    audio = tmp_path / "short.ogg"
    audio.write_bytes(b"fake")
    out_dir = tmp_path / "out"

    client = MagicMock()
    response = MagicMock()
    response.text = json.dumps({
        "summary": "short chat",
        "segments": [
            {"speaker": "Speaker 1", "timestamp": "00:05", "content": "hi"},
            {"speaker": "Speaker 2", "timestamp": "00:10", "content": "hey"},
        ],
    })
    client.models.generate_content.return_value = response
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    args = types.SimpleNamespace(
        prompt=None, audio=[str(audio)], youtube=[], model="flash",
        diarize=True, timestamps=True, output_dir=str(out_dir),
        chunk_len_sec=900, overlap_sec=30, no_chunking=False,
    )

    with patch("gski.audioscope.genai.Client", return_value=client), \
         patch("gski.audioscope_utils.probe_duration", return_value=60.0):
        cli.run(args)

    jsons = list(out_dir.glob("*.json"))
    raws = list(out_dir.glob("*.raw.txt"))
    subdirs = [p for p in out_dir.iterdir() if p.is_dir()]
    assert len(jsons) == 1, f"expected 1 json, got {jsons}"
    assert len(raws) == 1, f"expected 1 raw.txt, got {raws}"
    assert len(subdirs) == 0, f"expected no subdirs in short mode, got {subdirs}"

    data = json.loads(jsons[0].read_text())
    assert data["segments"][0]["speaker"] == "Speaker 1"
    assert data["segments"][0]["content"] == "hi"


def test_cli_no_chunking_flag_forces_short_path(tmp_path, monkeypatch):
    audio = tmp_path / "long.ogg"
    audio.write_bytes(b"fake")
    out_dir = tmp_path / "out"

    client = MagicMock()
    response = MagicMock()
    response.text = json.dumps({"summary": "", "segments": [
        {"speaker": "A", "timestamp": "00:00", "content": "x"},
    ]})
    client.models.generate_content.return_value = response
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    args = types.SimpleNamespace(
        prompt=None, audio=[str(audio)], youtube=[], model="flash",
        diarize=True, timestamps=True, output_dir=str(out_dir),
        chunk_len_sec=900, overlap_sec=30, no_chunking=True,
    )

    with patch("gski.audioscope.genai.Client", return_value=client), \
         patch("gski.audioscope_utils.probe_duration", return_value=7500.0):
        cli.run(args)

    subdirs = [p for p in out_dir.iterdir() if p.is_dir()]
    assert not subdirs, f"no-chunking must not create debug dir, got {subdirs}"
    assert list(out_dir.glob("*.json")), "short-mode json must still be produced"
