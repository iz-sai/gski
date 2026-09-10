---
name: gski nanobanana
description: Generate, edit, and understand images. Default skill for image generation and image editing tasks.
---

## How it works

`gski nanobanana` calls the Gemini API directly for image generation and editing. Output lands in `./nanobanana-output/`. Run from the directory where output should be saved.

Default model is `gemini-3.1-flash-image-preview` (`flash3`). Always use the default Flash 3 model. Do not use `--model pro`.

## Commands

```bash
gski nanobanana "prompt"                                # text-to-image
gski nanobanana "instruction" --image file.png          # edit existing image
gski nanobanana "prompt" --image a.png --image b.png    # multi-image composition
```

## Options

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--image FILE` | repeatable | none | input image(s) for editing |
| `--model` | `flash3`, `flash2` | `flash3` | default: flash3. Always use default Flash 3, do not use pro |
| `--aspect-ratio` | `1:1`,`2:3`,`3:2`,`3:4`,`4:3`,`4:5`,`5:4`,`9:16`,`16:9`,`21:9` | auto | output aspect ratio |
| `--size` | `1K`,`2K`,`4K` | `1K` | resolution (pro model only) |
| `--search` | flag | off | enable Google Search grounding |
| `--output-dir` | path | `./gski nanobanana-output` | where to save output |
| `-o`, `--output` | path | none | exact output file path; overrides `--output-dir` and auto-naming |

## Examples

```bash
# Generate
gski nanobanana "fox in snowy forest, watercolor style"
gski nanobanana "a modern logo for a coffee shop called 'The Daily Grind'"
gski nanobanana "isometric 3D miniature of Tokyo" --aspect-ratio 16:9

# Edit
gski nanobanana "add sunglasses to the person" --image photo.png
gski nanobanana "change the sofa to brown leather" --image room.png
gski nanobanana "restore to modern photo quality, full color" --image old_photo.jpg

# Multi-image
gski nanobanana "office group photo, funny faces" --image p1.png --image p2.png --image p3.png
gski nanobanana "put this logo on the product" --image product.png --image logo.png

# Search grounding
gski nanobanana "infographic of today's weather in San Francisco" --search

# Icons and assets
gski nanobanana "cute dog icon, colorful 3D style, white background" --aspect-ratio 1:1
gski nanobanana "seamless geometric triangle pattern, duotone" --aspect-ratio 1:1
```

## After generation

List `./nanobanana-output/` to see generated files. Do not read image files.

DO NOT READ LARGE IMAGES OVER 5MB — this breaks opencode sessions.
