---
name: gski audioscope
description: Transcribe and diarize audio — speech-to-text, speaker identification, timestamps
---

## Setup

Check: `which gski`
Install if missing: `pip install gski` (from the gski repo)
Requires `GEMINI_API_KEY` env var.

## How it works

`gski audioscope` sends audio files or YouTube URLs to Gemini and returns transcriptions. Supports speaker diarization (who said what) and timestamped segments via structured output.

Default model is `gemini-3-flash-preview`. For higher quality: `--model pro`.

Files under 15 MB are sent inline. Larger files are uploaded via the Files API automatically.

## Commands

```bash
# Plain transcription
gski audioscope --audio meeting.mp3

# Transcription with timestamps
gski audioscope --audio meeting.mp3 --timestamps

# Speaker diarization
gski audioscope --audio meeting.mp3 --diarize

# Diarization with timestamps
gski audioscope --audio meeting.mp3 --diarize --timestamps

# YouTube URL
gski audioscope --youtube "https://www.youtube.com/watch?v=..."

# Custom prompt
gski audioscope "summarize the key decisions" --audio meeting.mp3

# Multiple audio files
gski audioscope --audio part1.mp3 --audio part2.mp3 --diarize
```

## Options

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `prompt` | positional, optional | auto-selected | overrides default prompt |
| `--audio FILE` | repeatable | none | local audio file(s) |
| `--youtube URL` | repeatable | none | YouTube URL(s) |
| `--model` | `flash`, `pro` | `flash` | model selection |
| `--diarize` | flag | off | speaker identification (JSON output) |
| `--timestamps` | flag | off | add MM:SS timestamps to segments |
| `--output-dir` | path | `./output` | where to save output files |
| `--chunk-len-sec` | int | `900` | chunk length in seconds (long audio path) |
| `--overlap-sec` | int | `30` | overlap between chunks in seconds |
| `--no-chunking` | flag | off | force single-shot even for long audio |

## Output

- **Default mode**: plain transcript text to stdout, saved as `.txt`
- **`--diarize`**: formatted speaker-labeled transcript to stdout, structured JSON saved to `--output-dir`
- **`--timestamps`**: timestamps included in output segments
- All output files saved to `--output-dir` (created automatically)

### Output layout

**All diarize modes produce** `<output-dir>/audioscope_<TS>.json` — legacy dict shape
`{"summary": "", "segments": [{"speaker": "...", "timestamp": "...", "content": "..."}, ...]}`.
This is the file downstream scripts should read.

**Short-audio mode** additionally writes `audioscope_<TS>.raw.txt`
(raw Gemini response, used for debugging parse failures).

**Long-audio mode** (>~16 min, auto-triggered) additionally writes a
debug directory `audioscope_<TS>/` containing:
- `merged.json` — same segments in flat `{s,t,x}` schema
- `chunk_NNN.meta.json` — per-chunk retry attempts, strategies, validation reasons
- `chunk_NNN.raw.txt` — raw Gemini response for the last attempt of each chunk

Downstream consumers (meet-transcribe, vm-transcribe) see one `.json`
per run at the output root regardless of chunked/non-chunked mode — they
do not need to know which path was taken.

The system speaker `__system__` is used for gap/lost-chunk placeholders
injected automatically when the model skips audio or a chunk fails all
retries. Downstream formatters can filter these out or render them
distinctly; they are semantically "transcript coverage metadata", not
real speech.

## Supported formats

WAV, MP3, AIFF, AAC, OGG, FLAC

## Notes

- At least one `--audio` or `--youtube` is required
- `--diarize` and `--timestamps` can be combined
- Files over 15 MB are automatically uploaded via Gemini Files API
- Max audio length per prompt: 9.5 hours
- Gemini downsamples to 16 Kbps, merges multi-channel to mono
- ~32 tokens per second of audio
- Long audio (>~16 min) with `--diarize --timestamps` is automatically split into 15-min chunks with 30s overlap, transcribed sequentially with speaker-identity continuity, and merged. Disable with `--no-chunking`.
- Each chunk is validated (duration / 5-gram loop / coverage gap) and retried up to 3 times with seed/temperature perturbation on failure; best partial result is kept if all attempts fail.
