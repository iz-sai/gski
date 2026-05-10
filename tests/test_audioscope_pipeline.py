import json
from unittest.mock import MagicMock, patch

from gski.audioscope_pipeline import transcribe_long


def test_transcribe_long_single_chunk_short_audio(tmp_path):
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")

    client = MagicMock()
    response = MagicMock()
    response.text = '[{"s":"Speaker 1","t":"00:05","x":"hello"}]'
    response.candidates = [MagicMock(finish_reason="STOP")]
    response.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)
    client.models.generate_content.return_value = response
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=600):
        result = transcribe_long(
            client,
            audio_path=str(audio),
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
        )

    assert len(result["segments"]) == 1
    assert result["segments"][0]["x"] == "hello"
    assert len(result["chunks_meta"]) == 1
    assert result["num_chunks"] == 1


def test_transcribe_long_multi_chunk_success(tmp_path):
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    client = MagicMock()

    def fake_generate(model, contents, config):
        r = MagicMock()
        r.candidates = [MagicMock(finish_reason="STOP")]
        r.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)
        idx = client.models.generate_content.call_count - 1
        # Dense segments every minute so gap validator passes (max_gap=180s).
        segs = [
            '{"s":"Speaker 1","t":"00:05","x":"chunk ' + str(idx) + ' start"}'
        ]
        for m in range(1, 15):
            segs.append(
                '{"s":"Speaker 1","t":"' + f"{m:02d}:00" + '","x":"chunk ' + str(idx) + ' minute ' + str(m) + '"}'
            )
        segs.append('{"s":"Speaker 1","t":"14:50","x":"chunk ' + str(idx) + ' end"}')
        r.text = "[" + ",".join(segs) + "]"
        return r
    client.models.generate_content.side_effect = fake_generate
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=1770), \
         patch("gski.audioscope_pipeline.extract_chunk") as mock_extract:
        result = transcribe_long(
            client,
            audio_path=str(audio),
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
            chunk_len_sec=900, overlap_sec=30,
        )

    assert mock_extract.call_count == 2
    assert result["segments"][0]["t"] == "00:05"
    assert any("chunk 1 start" in s["x"] for s in result["segments"])
    assert result["num_chunks"] == 2


def test_transcribe_long_retries_failed_chunk(tmp_path):
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    client = MagicMock()

    bad = MagicMock()
    bad.text = '[{"s":"A","t":"00:00","x":"hi"}]'
    bad.candidates = [MagicMock(finish_reason="STOP")]
    bad.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=5)

    good0 = MagicMock()
    good0.text = '[{"s":"A","t":"14:50","x":"complete chunk 0"}]'
    good0.candidates = [MagicMock(finish_reason="STOP")]
    good0.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)

    good1 = MagicMock()
    good1.text = '[{"s":"A","t":"10:30","x":"complete chunk 1"}]'
    good1.candidates = [MagicMock(finish_reason="STOP")]
    good1.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)

    # duration=1500, chunk_len=900 → 2 chunks.
    # chunk 0: bad (fails duration) → good retry. chunk 1: good on first try.
    client.models.generate_content.side_effect = [bad, good0, good1]
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=1500), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset"):
        result = transcribe_long(
            client, audio_path=str(audio),
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
            chunk_len_sec=900, overlap_sec=30,
        )

    assert client.models.generate_content.call_count == 3
    chunk0_meta = result["chunks_meta"][0]
    assert len(chunk0_meta["attempts"]) == 2
    assert chunk0_meta["attempts"][0]["ok"] is False
    assert chunk0_meta["attempts"][1]["ok"] is True
    assert any("complete chunk 0" in s["x"] for s in result["segments"])
    assert any("complete chunk 1" in s["x"] for s in result["segments"])


def test_transcribe_long_rejects_looped_segments_as_fallback(tmp_path):
    """If Gemini MAX_TOKENS-es on a repeated word, the looped content must be
    cut and replaced with a placeholder — not leaked into merged output."""
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    client = MagicMock()

    # Build a segment where one token repeats thousands of times — classic
    # Gemini MAX_TOKENS loop on a single word.
    looped_text = "na " * 1200
    looped = MagicMock()
    looped.text = (
        '[{"s":"Speaker 1","t":"00:05","x":"hello clean prefix content"},'
        '{"s":"Speaker 2","t":"00:14","x":"intro words then ' + looped_text.strip() + '"}]'
    )
    looped.candidates = [MagicMock(finish_reason="STOP")]
    looped.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=8000)

    # Single chunk. Even one response is enough — salvage cuts the loop and
    # the chunk is accepted on attempt 0.
    client.models.generate_content.side_effect = [looped]
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=900), \
         patch("gski.audioscope_pipeline.extract_chunk"):
        result = transcribe_long(
            client, audio_path=str(audio),
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
            chunk_len_sec=900, overlap_sec=30,
        )

    assert result["num_chunks"] == 1
    # Loop must be gone; clean prefix preserved; placeholder inserted
    for seg in result["segments"]:
        assert "na na na na na" not in seg["x"].lower()
    joined = " ".join(s["x"] for s in result["segments"])
    assert "hello clean prefix content" in joined
    assert "intro words" in joined
    assert "[\u2026cut: repetition loop\u2026]" in joined


def test_retry_uses_audio_offset_on_second_attempt(tmp_path):
    """Attempt 1 must call extract_chunk_with_offset (audio-perturbation retry)."""
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    client = MagicMock()

    # Single chunk (900s). Attempt 0: gap failure (only 1 seg covers 15min).
    # Attempt 1 (audio_offset): dense segments → passes.
    bad = MagicMock()
    bad.text = '[{"s":"A","t":"00:00","x":"start only"}]'  # duration fail
    bad.candidates = [MagicMock(finish_reason="STOP")]
    bad.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=5)
    good_segs = [
        f'{{"s":"A","t":"{m:02d}:00","x":"minute {m}"}}' for m in range(15)
    ]
    good = MagicMock()
    good.text = "[" + ",".join(good_segs) + "]"
    good.candidates = [MagicMock(finish_reason="STOP")]
    good.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)

    client.models.generate_content.side_effect = [bad, good]
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=900), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset") as mock_off:
        transcribe_long(
            client, audio_path=str(audio),
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
        )

    # Attempt 0 uses default extraction; attempt 1 must invoke the offset variant.
    assert mock_off.call_count == 1
    kwargs = mock_off.call_args.kwargs
    assert kwargs.get("offset_sec") == 2


def test_retry_uses_prompt_variant_on_third_attempt(tmp_path):
    """Attempt 2 must pass extra anti-loop instruction via the prompt."""
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    client = MagicMock()

    # All three attempts return the same short (duration-fail) response so we
    # can inspect the prompt used on attempt 2.
    prompts_seen = []

    def fake_gen(model, contents, config):
        # contents is [audio_part, prompt_string]
        prompts_seen.append(contents[1])
        r = MagicMock()
        r.text = '[{"s":"A","t":"00:00","x":"hi"}]'
        r.candidates = [MagicMock(finish_reason="STOP")]
        r.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=5)
        return r

    client.models.generate_content.side_effect = fake_gen
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=900), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset"):
        transcribe_long(
            client, audio_path=str(audio),
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
        )

    # 3 attempts observed, and attempt 2 prompt contains the anti-loop suffix.
    assert len(prompts_seen) == 3
    assert "DO NOT repeat" in prompts_seen[2]
    assert "every minute must have at least one segment" in prompts_seen[2]
    # Attempt 0 and 1 prompts do NOT include the suffix
    assert "DO NOT repeat" not in prompts_seen[0]
    assert "DO NOT repeat" not in prompts_seen[1]


def test_transcribe_long_inserts_lost_chunk_placeholder(tmp_path):
    """If a chunk returns no segments after all retries, merged output must
    contain a __system__ placeholder marking the lost time range."""
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    client = MagicMock()

    # Chunk 0: good. Chunk 1: all retries raise JSON error → empty segments.
    good_segs = [
        f'{{"s":"A","t":"{m:02d}:00","x":"m{m}"}}' for m in range(15)
    ]
    good = MagicMock()
    good.text = "[" + ",".join(good_segs) + "]"
    good.candidates = [MagicMock(finish_reason="STOP")]
    good.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
    bad = MagicMock()
    bad.text = "total garbage not json"
    bad.candidates = [MagicMock(finish_reason="MAX_TOKENS")]
    bad.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=32000)
    # duration=1770 → 2 chunks. Chunk 0: good. Chunk 1: bad × 3 retries.
    client.models.generate_content.side_effect = [good, bad, bad, bad]
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=1770), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset"):
        result = transcribe_long(
            client, audio_path=str(audio),
            model="gemini-3-flash-preview",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
        )

    # merged output must contain the __system__ lost-chunk marker.
    texts = [s["x"] for s in result["segments"]]
    assert any("chunk lost" in t.lower() for t in texts)
    # system segment must have __system__ speaker.
    for s in result["segments"]:
        if "chunk lost" in s["x"].lower():
            assert s["s"] == "__system__"
            break
    else:
        raise AssertionError("no lost-chunk marker found")
    # warnings list must mention the placeholder
    assert any("lost-chunk placeholder" in w or "no valid segments" in w
               for w in result["warnings"])


def test_flat_to_legacy_converts_keys_and_wraps_in_dict():
    from gski.audioscope_pipeline import flat_segments_to_legacy_dict
    flat = [
        {"s": "Speaker 1", "t": "00:05", "x": "hello"},
        {"s": "Speaker 2", "t": "00:14", "x": "world"},
    ]
    out = flat_segments_to_legacy_dict(flat)
    assert isinstance(out, dict)
    assert out.get("summary") == ""
    assert out["segments"] == [
        {"speaker": "Speaker 1", "timestamp": "00:05", "content": "hello"},
        {"speaker": "Speaker 2", "timestamp": "00:14", "content": "world"},
    ]


def test_flat_to_legacy_preserves_system_speaker():
    from gski.audioscope_pipeline import flat_segments_to_legacy_dict
    flat = [
        {"s": "__system__", "t": "47:33", "x": "[\u2026gap: 14m 53s untranscribed\u2026]"},
    ]
    out = flat_segments_to_legacy_dict(flat)
    assert out["segments"][0]["speaker"] == "__system__"
    assert out["segments"][0]["content"].startswith("[\u2026gap:")


def test_flat_to_legacy_handles_missing_timestamp():
    from gski.audioscope_pipeline import flat_segments_to_legacy_dict
    flat = [{"s": "A", "x": "no ts here"}]  # t missing (diarize without timestamps)
    out = flat_segments_to_legacy_dict(flat)
    assert out["segments"][0]["timestamp"] == ""
    assert out["segments"][0]["speaker"] == "A"
    assert out["segments"][0]["content"] == "no ts here"


def test_flat_to_legacy_empty_list():
    from gski.audioscope_pipeline import flat_segments_to_legacy_dict
    out = flat_segments_to_legacy_dict([])
    assert out == {"summary": "", "segments": []}


def test_cli_chunked_writes_legacy_json_at_output_root(tmp_path, monkeypatch):
    import types
    from gski import audioscope as cli

    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")
    out_dir = tmp_path / "out"

    client = MagicMock()
    def fake_generate(model, contents, config):
        r = MagicMock()
        r.candidates = [MagicMock(finish_reason="STOP")]
        r.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
        idx = client.models.generate_content.call_count - 1
        segs = [
            f'{{"s":"Speaker 1","t":"{m:02d}:00","x":"chunk {idx} min {m}"}}'
            for m in range(15)
        ]
        r.text = "[" + ",".join(segs) + "]"
        return r
    client.models.generate_content.side_effect = fake_generate
    client.files.upload.return_value = MagicMock()

    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    args = types.SimpleNamespace(
        prompt=None, audio=[str(audio)], youtube=[], model="flash",
        diarize=True, timestamps=True, output_dir=str(out_dir),
        chunk_len_sec=900, overlap_sec=30, no_chunking=False,
    )

    with patch("gski.audioscope.genai.Client", return_value=client), \
         patch("gski.audioscope_utils.probe_duration", return_value=1770), \
         patch("gski.audioscope_pipeline.probe_duration", return_value=1770), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset"):
        cli.run(args)

    top_json = list(out_dir.glob("audioscope_*.json"))
    debug_dirs = [p for p in out_dir.iterdir() if p.is_dir() and p.name.startswith("audioscope_")]
    assert len(top_json) == 1, f"expected 1 top-level json, got {top_json}"
    assert len(debug_dirs) == 1, f"expected 1 debug dir, got {debug_dirs}"
    assert top_json[0].stem == debug_dirs[0].name

    data = json.loads(top_json[0].read_text())
    assert isinstance(data, dict)
    assert "segments" in data
    assert data["segments"]
    first = data["segments"][0]
    assert set(first.keys()) >= {"speaker", "timestamp", "content"}
    assert first["speaker"] == "Speaker 1"
    assert first["content"].startswith("chunk 0 min")


def test_coverage_summary_reports_gaps_and_lost_chunks():
    from gski.audioscope_pipeline import summarize_coverage
    merged = [
        {"s": "A", "t": "00:00", "x": "a"},
        {"s": "__system__", "t": "02:00", "x": "[\u2026gap: 3m 36s untranscribed\u2026]"},
        {"s": "B", "t": "05:36", "x": "b"},
        {"s": "__system__", "t": "10:00", "x": "[\u2026chunk lost: 600s\u2013900s, all retries failed\u2026]"},
        {"s": "C", "t": "15:00", "x": "c"},
    ]
    cov = summarize_coverage(merged)
    assert cov["gap_count"] == 1
    assert cov["lost_chunk_count"] == 1
    assert cov["gap_seconds"] == 216  # 3m 36s
    assert cov["lost_chunk_seconds"] == 300  # 900 - 600
    assert cov["total_untranscribed_sec"] == 516


def test_coverage_summary_zero_when_clean():
    from gski.audioscope_pipeline import summarize_coverage
    merged = [
        {"s": "A", "t": "00:00", "x": "hi"},
        {"s": "B", "t": "00:05", "x": "hey"},
    ]
    cov = summarize_coverage(merged)
    assert cov == {
        "gap_count": 0, "lost_chunk_count": 0,
        "gap_seconds": 0, "lost_chunk_seconds": 0,
        "total_untranscribed_sec": 0,
    }


def test_transcribe_long_emits_coverage_warning_when_gaps_present(tmp_path):
    from gski.audioscope_pipeline import transcribe_long
    audio = tmp_path / "x.ogg"
    audio.write_bytes(b"fake")

    client = MagicMock()
    # Return sparse segments so _insert_gap_placeholders creates a gap.
    def fake_generate(model, contents, config):
        r = MagicMock()
        r.candidates = [MagicMock(finish_reason="STOP")]
        r.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)
        idx = client.models.generate_content.call_count - 1
        # First chunk: dense segments. Second chunk: starts 5 minutes after prev ends → gap.
        if idx == 0:
            segs = [f'{{"s":"Speaker 1","t":"{m:02d}:00","x":"chunk 0 min {m}"}}' for m in range(15)]
        else:
            segs = [f'{{"s":"Speaker 1","t":"20:00","x":"chunk 1 late"}}']
        r.text = "[" + ",".join(segs) + "]"
        return r
    client.models.generate_content.side_effect = fake_generate
    client.files.upload.return_value = MagicMock()

    with patch("gski.audioscope_pipeline.probe_duration", return_value=1770), \
         patch("gski.audioscope_pipeline.extract_chunk"), \
         patch("gski.audioscope_pipeline.extract_chunk_with_offset"):
        result = transcribe_long(
            client, audio_path=str(audio), model="flash",
            diarize=True, timestamps=True,
            tmp_dir=tmp_path, output_dir=tmp_path / "out",
        )

    # Expect coverage summary warning string with "untranscribed" keyword.
    cov_warns = [w for w in result["warnings"] if "untranscribed" in w.lower()]
    assert cov_warns, f"expected coverage warning, got: {result['warnings']}"
    assert "coverage" in result
    assert result["coverage"]["gap_count"] >= 1


def test_chunk_is_unhealthy_all_attempts_failed():
    from gski.audioscope_pipeline import _chunk_is_unhealthy
    record = {
        "chunk": {"index": 0, "start": 0, "end": 900},
        "attempts": [
            {"attempt": 0, "ok": False, "failed_check": "loop"},
            {"attempt": 1, "ok": False, "failed_check": "loop"},
            {"attempt": 2, "ok": False, "failed_check": "loop"},
        ],
    }
    assert _chunk_is_unhealthy(record) is True


def test_chunk_is_unhealthy_last_attempt_ok():
    from gski.audioscope_pipeline import _chunk_is_unhealthy
    record = {
        "chunk": {"index": 0, "start": 0, "end": 900},
        "attempts": [
            {"attempt": 0, "ok": False, "failed_check": "loop"},
            {"attempt": 1, "ok": True, "failed_check": None},
        ],
    }
    assert _chunk_is_unhealthy(record) is False


def test_chunk_is_unhealthy_no_attempts():
    from gski.audioscope_pipeline import _chunk_is_unhealthy
    assert _chunk_is_unhealthy({"chunk": {"index": 0}, "attempts": []}) is True
