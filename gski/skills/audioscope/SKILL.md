---
name: gski audioscope
description: Transcribe audio/video with speaker diarization and word timestamps, or find and cut out non-verbal sounds (growls, gasps, grunts, anything you describe)
---

## Modes

`gski audioscope` has two modes. Input is any audio or video file; ffmpeg converts it to 16 kHz mono mp3 and splits it into chunks (default 1600 s, because `gemini-3.5-transcribe` caps diarization/word timestamps at 30 min). Results go to `<output-dir>/<file stem>/`.

### transcribe

Verbatim transcript via `gemini-3.5-transcribe`, with speaker diarization and word-level timestamps by default. Words are grouped into segments (same speaker, gap <= `--gap`).

```bash
gski audioscope transcribe episode.mp4 --lang ru-RU
gski audioscope transcribe meeting.mp3                 # auto language
gski audioscope transcribe talk.mp3 --smart            # cleaned-up plain text, no speakers/timestamps
gski audioscope transcribe long.mp4 --no-diarize --chunk 1200
```

Outputs: `transcript.json` (`segments`, `words`, `text`, `config`) and `transcript.txt` (`[MM:SS.s] spk:N: text`, also printed to stdout).

Notes:
- Timestamps are absolute (chunk offset already added).
- Speaker ids (`spk:0`, ...) are assigned per chunk and do not match across chunks. Each segment carries a `chunk` field; identify who is who per chunk (e.g. by content cues).
- `--smart` is incompatible with diarization/timestamps and disables them.
- Word timestamps may slightly reduce accuracy; use `--no-timestamps` if text quality matters more.

### sounds

Finds non-verbal sounds (growls, gasps, grunts, sighs, whatever you describe) in an audio or video file. Gemini (default `gemini-3.8-flash`) listens to the audio and returns the time range of each matching sound. The result is printed and saved; with `--extract` each sound is also cut out with ffmpeg (mp3, plus mp4 if the input has video), padded by `--pad` seconds.

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

Shared:

| Flag | Default | Notes |
|------|---------|-------|
| `FILE` | required | audio or video |
| `--chunk SECS` | 1600 | chunk length |
| `--output-dir DIR` | `./output` | results in `DIR/<stem>/` |

transcribe: `--lang BCP47` (default auto), `--no-diarize`, `--no-timestamps`, `--smart`, `--gap SECS` (1.2).

sounds: `--like TEXT`, `--context TEXT`, `--extract`, `--pad SECS` (0.5), `--model flash|pro` (flash).

## Requirements

- `GEMINI_API_KEY`
- `ffmpeg` and `ffprobe` in PATH
- For YouTube, download audio first: `gski youtube-scope <url> --audio`, then pass the file
