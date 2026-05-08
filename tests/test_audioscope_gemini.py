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
