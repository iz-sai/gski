---
name: gski nanoscope
description: Understand and analyze images and videos with Gemini (captioning, timestamps, object detection, segmentation). Use ONLY when explicitly asked by the user; do not invoke proactively.
---

Use `gski nanoscope` ONLY when explicitly requested by the user. Do not invoke on your own.

```bash
# Images
gski nanoscope "PROMPT" --image FILE [--image FILE]... [--url URL]...
gski nanoscope "PROMPT" --image FILE --detect
gski nanoscope "PROMPT" --image FILE --segment [--output-dir DIR]

# Videos (defaults: --model 3-8 --target-res 480p --fps 1.0 --media-res low, audio kept, static mode)
gski nanoscope "PROMPT" --video FILE
gski nanoscope "PROMPT" --video FILE --agentic
gski nanoscope "PROMPT" --video FILE --start 00:00 --end 30:00
gski nanoscope "PROMPT" --video FILE --fps 0.5 --target-res 360p --no-audio --media-res high --model argon
```

Flags:
- `--image FILE` (repeatable): local image or URL
- `--video FILE` (repeatable): local video, public HTTPS URL, or YouTube URL
- `--url URL` (repeatable): image URL
- `--model 3-8|argon`: `gemini-3.8-flash` (default `3-8`) or `gemini-4-argon` (`argon`)
- `--media-res low|medium|high|ultra_high`: API frame token budget (default `low`=66 tok/frame, `high`=258 tok/frame)
- `--fps FLOAT`: local transcode & static sampling rate (default `1.0`)
- `--target-res 360p|480p|720p|1080p|original`: local ffmpeg height before Files API upload (default `480p`)
- `--agentic`: dynamic timeline navigation (`processing: "agentic"`, up to 88% fewer tokens on long videos)
- `--no-audio`: strip audio track during transcode (saves 32 tok/s)
- `--start TIME` / `--end TIME`: clip window in seconds or `MM:SS` (static mode only; reuses cached upload)
- `--detect`: JSON object detection (`boxes` with `box_2d` `[ymin, xmin, ymax, xmax]` 0-1000 and `label`)
- `--segment`: polygon segmentation masks + overlays saved to `--output-dir` (default `./output`), prints paths
- `--output-dir DIR`: output directory for `--segment`

Behavior:
- Local videos transcode via `ffmpeg` (auto-uses Intel VAAPI `/dev/dri/renderD128` + `-skip_frame noref` when available, fallback `libx264 -crf 28 -preset veryfast`; skipped if input `.mp4` is already `<= target-res` and `<= fps`) + mono 16kHz AAC `24k` audio, then upload via Gemini Files API (`client.files.upload`, max 2GB/20GB; raw HTTPS URLs cap at ~15MB) keyed by `display_name = <sha1>-<stem>_<res>_<fps>fps_a1.mp4`. Files API entries auto-expire in 48h and are reused across calls.
- Progress logs to `stderr` at 10% intervals.
- For dense timestamp extraction across long videos (>30m), keep static mode and run 20-30m windows with `--start` and `--end`. For targeted event search, use `--agentic`.
