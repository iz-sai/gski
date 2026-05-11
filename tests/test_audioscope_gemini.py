from unittest.mock import MagicMock

import pytest

from gski.audioscope_gemini import (
    build_diarize_config,
    build_prompt_for_chunk,
    transcribe_chunk,
    ChunkTranscriptionError,
)


def test_build_diarize_config_has_flat_schema_and_hardened_params():
    cfg = build_diarize_config(timestamps=True)
    assert cfg.response_mime_type == "application/json"
    schema = cfg.response_schema
    assert schema.type.name == "ARRAY"
    assert set(schema.items.properties.keys()) == {"s", "t", "x"}
    assert cfg.temperature == 0.0
    assert cfg.top_p == 0.0
    assert cfg.top_k == 1
    assert cfg.candidate_count == 1
    assert cfg.seed == 42


def test_build_diarize_config_flash_sets_thinking_budget_zero():
    cfg = build_diarize_config(timestamps=True, model="gemini-3-flash-preview")
    # Flash runs in non-thinking mode for speed.
    assert cfg.thinking_config is not None
    assert cfg.thinking_config.thinking_budget == 0


def test_build_diarize_config_pro_omits_thinking_config():
    # Pro rejects budget=0 with "This model only works in thinking mode".
    # We must omit thinking_config for pro so the server picks its default.
    cfg = build_diarize_config(timestamps=True, model="gemini-3-pro-preview")
    assert cfg.thinking_config is None


def test_build_prompt_includes_duration_hint():
    p = build_prompt_for_chunk(
        chunk_index=2, total_chunks=5,
        chunk_start_sec=1740, chunk_duration_sec=900,
        diarize=True, timestamps=True, prev_tail=None,
    )
    assert "900" in p or "15:00" in p or "15 min" in p.lower()
    assert "NEVER REPEAT" in p.upper()


def test_build_prompt_with_prev_tail_injects_context():
    p = build_prompt_for_chunk(
        chunk_index=1, total_chunks=2,
        chunk_start_sec=870, chunk_duration_sec=900,
        diarize=True, timestamps=True,
        prev_tail=[
            {"s": "Speaker 1", "t": "14:50", "x": "last words"},
            {"s": "Speaker 2", "t": "14:55", "x": "reply"},
        ],
    )
    assert "Speaker 1" in p
    assert "last words" in p


def test_build_prompt_appends_extra_instruction():
    p = build_prompt_for_chunk(
        chunk_index=0, total_chunks=2,
        chunk_start_sec=0, chunk_duration_sec=900,
        diarize=True, timestamps=True, prev_tail=None,
        extra_instruction="CRITICAL: anti-loop directive here",
    )
    assert "CRITICAL: anti-loop directive here" in p


def test_build_prompt_extra_instruction_none_by_default():
    p = build_prompt_for_chunk(
        chunk_index=0, total_chunks=1,
        chunk_start_sec=0, chunk_duration_sec=900,
        diarize=True, timestamps=True, prev_tail=None,
    )
    # Must not crash and must not include the extra marker
    assert "CRITICAL:" not in p


def test_transcribe_chunk_parses_valid_json():
    client = MagicMock()
    response = MagicMock()
    response.text = '[{"s":"Speaker 1","t":"00:05","x":"hi"}]'
    response.candidates = [MagicMock(finish_reason="STOP")]
    response.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)
    client.models.generate_content.return_value = response

    segs, meta = transcribe_chunk(
        client, model="gemini-3-flash-preview",
        audio_part=MagicMock(), config=None, prompt="test",
    )
    assert segs == [{"s": "Speaker 1", "t": "00:05", "x": "hi"}]
    assert meta["finish_reason"] == "STOP"
    assert meta["input_tokens"] == 100
    assert meta["output_tokens"] == 20


def test_transcribe_chunk_raises_on_invalid_json():
    client = MagicMock()
    response = MagicMock()
    response.text = '[{"s":"Sp'
    response.candidates = [MagicMock(finish_reason="MAX_TOKENS")]
    response.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=20)
    client.models.generate_content.return_value = response

    with pytest.raises(ChunkTranscriptionError) as e:
        transcribe_chunk(
            client, model="gemini-3-flash-preview",
            audio_part=MagicMock(), config=None, prompt="test",
        )
    assert e.value.meta["finish_reason"] == "MAX_TOKENS"
    assert "[{" in e.value.meta["raw_text"]


def test_transcribe_chunk_salvages_whitespace_truncated_response():
    """Whitespace-storm MAX_TOKENS must be repaired via salvage_raw_text
    and parse successfully, with meta['raw_salvaged']=True."""
    client = MagicMock()
    response = MagicMock()
    response.text = (
        '[{"s":"A","t":"00:00","x":"hello"},{"s":"B","t":"00:05","x":"world"}'
        + " " * 3000
    )
    response.candidates = [MagicMock(finish_reason="MAX_TOKENS")]
    response.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=32000)
    client.models.generate_content.return_value = response

    segs, meta = transcribe_chunk(
        client, model="gemini-3-flash-preview",
        audio_part=MagicMock(), config=None, prompt="test",
    )
    assert len(segs) == 2
    assert segs[-1]["x"] == "world"
    assert meta["raw_salvaged"] is True
