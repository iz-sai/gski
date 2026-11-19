---
name: gski audioscope
description: Transcribe and diarize audio — speech-to-text, speaker identification, timestamps
---

## How it works

`gski audioscope` sends audio files or YouTube URLs to Gemini and returns transcriptions. Supports speaker diarization (who said what) and timestamped segments via structured output.

Default model is `gemini-4-hydrogen` (`--model flash` / `hydrogen`); `--model pro` / `carbon` uses `gemini-4-carbon`.

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

### Submodes (`transcribe` & `sounds`)

#### `transcribe` (`gemini-3.5-transcribe`)

Verbatim transcript via `gemini-3.5-transcribe` (Interactions API), with speaker diarization and word-level timestamps by default:

```bash
gski audioscope transcribe meeting.mp3                 # auto language
gski audioscope transcribe episode.mp4 --lang ru-RU
gski audioscope transcribe talk.mp3 --smart            # cleaned-up plain text, no speakers/timestamps
```

Outputs: `transcript.json` (`segments`, `words`, `text`, `config`) and `transcript.txt` (`[MM:SS.s] spk:N: text`, also printed to stdout).

Notes:
- Timestamps are absolute (chunk offset already added).
- Speaker ids (`spk:0`, ...) are assigned per chunk and do not match across chunks. Each segment carries a `chunk` field; identify who is who per chunk (e.g. by content cues).
- `--smart` is incompatible with diarization/timestamps and disables them.
- Word timestamps may slightly reduce accuracy; use `--no-timestamps` if text quality matters more.

#### `sounds`

Finds non-verbal sounds (growls, gasps, grunts, sighs, whatever you describe) in an audio or video file. Gemini (default `gemini-4-hydrogen`) listens to the audio and returns the time range of each matching sound. The result is printed and saved; with `--extract` each sound is also cut out with ffmpeg (mp3, plus mp4 if the input has video), padded by `--pad` seconds.

What counts as a match is up to you: describe it with `--like`, add background with `--context`. To limit how many come back, say so in `--like` (e.g. "the 3 most extreme groans").

```bash
# list matches, cut nothing
gski audioscope sounds episode.mp4 --context "Russian TV show, host Leonid Yakubovich"

# list and cut
gski audioscope sounds episode.mp4 --extract

# custom target
gski audioscope sounds podcast.mp3 --like "sighs and exaggerated yawns" --extract --pad 1
```

Outputs: `sounds.json` (start/end seconds and MM:SS, phonetic `sound`, `description`, `slug`, and file paths when extracted) and `sounds/sample_NN_<slug>.mp3|mp4`.

Notes:
- Zero results is valid; the model is told to return nothing rather than invent.
- The model gives times in MM:SS, so expect about a second of error; `--pad` covers it. Listen to a cut before trusting it.
- The default `--like` targets bizarre expressive vocalizations. Plain speech and ordinary laughter are excluded by the prompt.
- The file is scanned in chunks (`--chunk`, default 1600 s), same as `transcribe`.

## Options

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `prompt` | positional, optional | auto-selected | overrides default prompt, or `transcribe` / `sounds` |
| `--audio FILE` | repeatable | none | local audio file(s) |
| `--youtube URL` | repeatable | none | YouTube URL(s) |
| `--model` | `flash`, `pro`, `hydrogen`, `carbon` | `flash` (`gemini-4-hydrogen`) | model selection |
| `--diarize` | flag | off | speaker identification (JSON output) |
| `--timestamps` | flag | off | add MM:SS timestamps to segments |
| `--output-dir` | path | `./output` | where to save output files |
| `--chunk-len-sec` | int | `900` | chunk length in seconds (long audio path) |
| `--overlap-sec` | int | `30` | overlap between chunks in seconds |
| `--no-chunking` | flag | off | force single-shot even for long audio |

Submode flags:
- `transcribe`: `--lang BCP47` (default auto), `--no-diarize`, `--no-timestamps`, `--smart`, `--gap SECS` (1.2), `--chunk SECS` (1600).
- `sounds`: `--like TEXT`, `--context TEXT`, `--extract`, `--pad SECS` (0.5), `--model hydrogen|carbon` (hydrogen), `--chunk SECS` (1600).

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

## Salvage mode

Opt-in, for when you cannot tolerate untranscribed segments. Adds
significant API cost (pro model is ~10x flash).

```
--salvage                     enable salvage ladder (default: off)
--salvage-model pro           model for pro fallback (default: pro)
--salvage-subchunk-sec 180    sub-chunk length in seconds (default: 180)
--salvage-max-depth 2         ladder depth 1-3 (default: 2)
```

When enabled, after the initial chunking pass, any chunk whose final
retry attempt failed validation (or produced a lost-chunk placeholder)
is retried on the salvage model (default: pro). If pro also fails, the
chunk is split into `salvage-subchunk-sec`-long slices and each is
transcribed separately on flash. Depth 3 adds a pro pass over the
sub-chunks as a final backstop.

Per-chunk salvage metadata is recorded in `chunk_NNN.meta.json` under
a new `salvage` key (`pro`, `subchunk_flash`, `subchunk_pro` sub-keys
with `ok` / `segment_count` / `attempts`). Stderr prints one line per
recovered chunk: `chunk N salvaged via pro-fallback (M segments)`.

Empirically on 2h Russian meeting audio, depth=2 closes 100% of gaps
from flash-only validation failures: pro recovers ~2 out of 3 failing
chunks; the remaining one is recovered by flash sub-chunking.

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
