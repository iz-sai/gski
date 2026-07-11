---
name: gski nanoscope
description: Understand and analyze images — captioning, comparison, object detection, segmentation
---

## Setup

Check: `which gski`
Install if missing: `pip install gski` (from the gski repo)
Requires `GEMINI_API_KEY` env var.

## How it works

`gski nanoscope` sends images + a text prompt to Gemini's multimodal models and returns text or structured analysis. Unlike nanobanana (which generates images), nanoscope analyzes existing images.

Default model is `gemini-3.5-flash`. For higher quality: `--model pro`.

## Commands

```bash
# Describe / caption
gski nanoscope "what's in this image?" --image photo.png
gski nanoscope "describe the mood and composition" --image painting.jpg

# Compare multiple images
gski nanoscope "what changed between these two?" --image before.png --image after.png

# Analyze image from URL
gski nanoscope "what is this?" --url https://example.com/image.jpg

# Object detection (JSON bounding boxes)
gski nanoscope "detect all objects" --image scene.png --detect

# Segmentation (mask + overlay PNGs saved to disk)
gski nanoscope "segment the wooden and glass items" --image room.png --segment
```

## Options

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--image FILE` | repeatable | none | local input image(s) |
| `--url URL` | repeatable | none | image URL(s) to fetch and analyze |
| `--model` | `flash`, `pro` | `flash` | model selection |
| `--detect` | flag | off | object detection mode (JSON output) |
| `--segment` | flag | off | segmentation mode (saves PNGs) |
| `--output-dir` | path | `./nanoscope-output` | where segmentation saves masks/overlays |

## Output

- **Default mode**: text to stdout
- **`--detect`**: JSON array of objects with `box_2d` ([ymin, xmin, ymax, xmax] normalized 0-1000) and `label`
- **`--segment`**: saves mask PNGs and overlay PNGs to `--output-dir`, prints file paths to stdout. Requires `--image` (local file).

## Notes

- `--detect` and `--segment` are mutually exclusive
- At least one `--image` or `--url` is required
- `--segment` requires at least one local `--image` (not `--url`)
- Images are thumbnailed to 1024x1024 before segmentation
- Mix `--image` and `--url` freely in describe/compare mode
