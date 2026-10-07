---
name: gski nanobanana
description: Generate, edit, and understand images. Default skill for image generation and image editing tasks.
---

## How it works

`gski nanobanana` calls the Gemini API directly for image generation and editing. Output lands in `./nanobanana-output/`. Run from the directory where output should be saved.

Default model is `gemini-nano-banana-2.1` (`banana2.1`). Always use the default model `banana2.1`. Usage of older models (`flash3`, `flash2`, `pro`, `gemini-3.1-flash-image`, `gemini-2.5-flash-image`, `gemini-3-pro-image`, `gemini-3.1-flash-lite-image`) is strictly prohibited. Do not pass `--model flash3`, `--model flash2`, `--model pro`, or request earlier generation models.

## Commands

```bash
gski nanobanana "prompt"                                # text-to-image
gski nanobanana "instruction" --image file.png          # edit existing image
gski nanobanana "prompt" --image a.png --image b.png    # multi-image composition
```

## Options

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--image FILE` | repeatable | none | input image(s) for editing (up to 14 reference images) |
| `--model` | `banana2.1` | `banana2.1` | default: banana2.1 (`gemini-nano-banana-2.1`). Older models (flash3, flash2, pro) are prohibited |
| `--aspect-ratio` | `1:1`,`2:3`,`3:2`,`3:4`,`4:3`,`4:5`,`5:4`,`9:16`,`16:9`,`21:9` | auto | output aspect ratio |
| `--size` | `1K`,`2K`,`4K` | `1K` | output resolution: 1K, 2K, 4K |
| `--search` | flag | off | enable Google Search grounding (web & image search) |
| `--output-dir` | path | `./output` | where to save output |
| `-o`, `--output` | path | none | exact output file path; overrides `--output-dir` and auto-naming |

## Prompting guide

### 1. Structure and visual details
- **Natural language over tags**: Avoid empty keywords ("8k, photorealistic, masterpiece"). Describe concrete scene attributes: subject, action/pose, environment, lighting, camera angle, and lens (e.g. `wide-angle shot`, `low perspective`, `50mm lens`, `soft natural light`).
- **Templates**:
  - Photorealistic: `A [type of shot] of [subject] in [setting]. [Lighting description]. Shot from [camera angle] with [lens type].`
  - Stylized/Sticker: `A [style] sticker/illustration of [subject] [doing action]. Bold clean outlines, simple cel-shading, vibrant colors, solid white background.`

### 2. Exact text rendering
- Put target wording in quotes: `"The Daily Grind"`.
- Descriptively specify typography, weight, color, and layout: `clean, bold, sans-serif font in black and white, centered`.
- Explicitly state exclusions if needed: `No other text, no extra logos`.

### 3. Semantic inpainting (edits without masks)
- Gemini does not use separate binary mask files. Use conversational semantic masking:
  `Using the provided image, change ONLY [specific element] to [new description]. Keep everything else in the image exactly the same, preserving original style, lighting, and composition.`

### 4. Multi-image composition (up to 14 references)
- Supports up to 10 object fidelity references and up to 4 character consistency references.
- Refer to inputs by order or role:
  `Take the blue floral dress from the first image and have the woman from the second image wear it. Adjust lighting and shadows to match.`
- For character consistency across angles: feed the previous output and specify the new angle (`studio portrait of this character, in profile looking right, white background`).

### 5. Grounding with Search
- Pass `--search` to ground generation with Google Search (web and image retrieval).
- Use for real-time factual diagrams (weather, stocks, news) or accurate visual references: `Use search to find accurate images of a resplendent quetzal bird. Create a 3:2 wallpaper...`

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
