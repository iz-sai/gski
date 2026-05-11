import json

from google.genai import types

from gski.audioscope_salvage import salvage_raw_text


FLAT_DIARIZE_TS_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "s": types.Schema(type=types.Type.STRING, description="Speaker"),
            "t": types.Schema(type=types.Type.STRING, description="MM:SS timestamp"),
            "x": types.Schema(type=types.Type.STRING, description="Transcribed text"),
        },
        required=["s", "t", "x"],
    ),
)

FLAT_DIARIZE_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "s": types.Schema(type=types.Type.STRING),
            "x": types.Schema(type=types.Type.STRING),
        },
        required=["s", "x"],
    ),
)


def _thinking_config_kwargs(model: str | None = None):
    # Pro models require thinking mode (budget > 0 or dynamic); passing
    # budget=0 yields "400 Budget 0 is invalid. This model only works in
    # thinking mode." Omit the thinking config entirely for pro so the
    # server uses its default.
    if model and "pro" in model:
        return {}
    if not hasattr(types, "ThinkingConfig"):
        return {}
    try:
        return {"thinking_config": types.ThinkingConfig(thinking_budget=0)}
    except (TypeError, AttributeError):
        return {}


def build_diarize_config(
    timestamps: bool,
    *,
    seed: int = 42,
    temperature: float = 0.0,
    max_output_tokens: int = 32000,
    model: str | None = None,
):
    schema = FLAT_DIARIZE_TS_SCHEMA if timestamps else FLAT_DIARIZE_SCHEMA
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
        top_p=0.0,
        top_k=1,
        candidate_count=1,
        seed=seed,
        max_output_tokens=max_output_tokens,
        **_thinking_config_kwargs(model),
    )


ANTI_LOOP_DIRECTIVE = (
    "IMPERATIVE DIRECTIVE: NEVER REPEAT. If you detect that you are transcribing "
    "the same sequence of words in an unnatural and repetitive manner, interpret "
    "this as a signal of incomprehensible audio. Immediately break the loop, output "
    "[incomprehensible], and proceed to the next distinct segment. "
    "Do not paraphrase to fill gaps. Transcribe exactly what is said, in the original language."
)


def build_prompt_for_chunk(
    *,
    chunk_index: int,
    total_chunks: int,
    chunk_start_sec: int,
    chunk_duration_sec: int,
    diarize: bool,
    timestamps: bool,
    prev_tail: list[dict] | None = None,
    extra_instruction: str | None = None,
) -> str:
    mins = chunk_duration_sec // 60
    secs = chunk_duration_sec % 60
    dur_str = f"{mins:02d}:{secs:02d}"

    parts = [ANTI_LOOP_DIRECTIVE]

    if total_chunks > 1:
        parts.append(
            f"This audio is chunk {chunk_index + 1} of {total_chunks} from a longer recording. "
            f"It is exactly {dur_str} long ({chunk_duration_sec} seconds). "
            f"Transcribe it completely from 00:00 to {dur_str}. "
            f"Timestamps must be RELATIVE to this chunk (start at 00:00), not to the full recording."
        )
    else:
        parts.append(
            f"This audio is exactly {dur_str} long. "
            f"Transcribe it completely from 00:00 to {dur_str}."
        )

    if diarize and timestamps:
        parts.append(
            "Generate a transcript with speaker diarization. "
            "Label each speaker (Speaker 1, Speaker 2, etc). "
            "Group consecutive speech by the same speaker into segments. "
            "Provide accurate MM:SS timestamps for each segment."
        )
    elif diarize:
        parts.append(
            "Generate a transcript with speaker diarization. "
            "Label each speaker (Speaker 1, Speaker 2, etc)."
        )
    elif timestamps:
        parts.append(
            "Generate a transcript with accurate MM:SS timestamps for each segment."
        )
    else:
        parts.append("Generate a transcript of the speech.")

    if prev_tail:
        tail_str = "\n".join(
            f"[{s.get('t', '')}] {s.get('s', 'Speaker')}: {s.get('x', '')}"
            for s in prev_tail
        )
        parts.append(
            "Previous chunk ended with these utterances. "
            "Maintain consistent speaker identities (same voice = same Speaker N label). "
            "Do NOT re-transcribe these — start after them:\n" + tail_str
        )

    if extra_instruction:
        parts.append(extra_instruction)

    return "\n\n".join(parts)


class ChunkTranscriptionError(Exception):
    def __init__(self, message: str, meta: dict):
        super().__init__(message)
        self.meta = meta


def _response_meta(response) -> dict:
    finish = None
    try:
        finish = str(response.candidates[0].finish_reason)
    except (AttributeError, IndexError, TypeError):
        pass
    usage = getattr(response, "usage_metadata", None)
    return {
        "finish_reason": finish,
        "input_tokens": getattr(usage, "prompt_token_count", None),
        "output_tokens": getattr(usage, "candidates_token_count", None),
        "raw_text": response.text or "",
    }


def transcribe_chunk(client, *, model, audio_part, config, prompt):
    contents = [audio_part, prompt]
    response = client.models.generate_content(
        model=model, contents=contents, config=config,
    )
    meta = _response_meta(response)

    repaired, raw_salvaged = salvage_raw_text(meta["raw_text"])
    meta["raw_salvaged"] = raw_salvaged

    try:
        data = json.loads(repaired)
    except (json.JSONDecodeError, TypeError) as e:
        raise ChunkTranscriptionError(f"invalid JSON: {e}", meta) from e

    if not isinstance(data, list):
        raise ChunkTranscriptionError(
            f"expected JSON array, got {type(data).__name__}", meta
        )

    return data, meta
