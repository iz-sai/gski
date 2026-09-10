---
name: gski gptimage2
description: Generate and edit images with OpenAI GPT Image (gpt-image-2). Use ONLY when explicitly asked to use GPT Image or OpenAI for image generation.
---

## How it works

`gski gptimage2` calls the OpenAI Image API directly. Output lands in `./output/`. Run from the directory where output should be saved.

Default model is `gpt-image-2`. Earlier models: `gpt-image-1.5`, `gpt-image-1`, `gpt-image-1-mini`.

For Gemini-based image generation, use `gski nanobanana` instead.

## Commands

```bash
gski gptimage2 "prompt"                                 # text-to-image
gski gptimage2 "instruction" --image file.png           # edit existing image
gski gptimage2 "prompt" --image a.png --image b.png     # multi-image composition
gski gptimage2 "replace the pool" --image room.png --mask mask.png   # masked edit
```

## Options

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--image FILE` | repeatable | none | input image(s); triggers edit mode |
| `--mask FILE` | path | none | masked edit; applies to first `--image` |
| `--model` | `gpt-image-2`, `gpt-image-1.5`, `gpt-image-1`, `gpt-image-1-mini` | `gpt-image-2` | |
| `--size` | `auto`, `1024x1024`, `1536x1024`, `1024x1536`, `2048x2048`, `3840x2160`, `2160x3840`, or any `WxH` | `auto` | edges multiples of 16, max edge 3840, ratio ≤ 3:1 |
| `--quality` | `auto`, `low`, `medium`, `high` | `auto` | |
| `--format` | `jpg`, `png`, `webp` | `jpg` | |
| `--compression` | `0-100` | none | jpg/webp only |
| `--background` | `auto`, `opaque` | `auto` | gpt-image-2 does not support transparent |
| `-n N` | integer | `1` | number of images |
| `--output-dir` | path | `./output` | |
| `-o`, `--output` | path | none | exact output file path; overrides `--output-dir` and auto-naming |

## Mask requirements

- Image and mask must be the same format and size (<50MB).
- Mask must have an alpha channel; transparent pixels = areas to edit.

## Examples

```bash
# Generate
gski gptimage2 "a children's book drawing of a vet listening to a baby otter"
gski gptimage2 "isometric 3D miniature of Tokyo, 4K" --size 3840x2160 --quality high
gski gptimage2 "fast draft of a coffee mug on a table" --quality low

# Edit
gski gptimage2 "add sunglasses to the person" --image photo.png
gski gptimage2 "a sunlit lounge with a flamingo in the pool" \
  --image sunlit_lounge.png --mask mask.png --quality high

# Multi-image composition
gski gptimage2 "gift basket labeled 'Relax & Unwind' with ribbon, containing all items" \
  --image body-lotion.png --image bath-bomb.png --image incense-kit.png --image soap.png
```

## After generation

List `./output/` to see generated files. Do not read image files.

DO NOT READ LARGE IMAGES OVER 5MB — this breaks opencode sessions.
