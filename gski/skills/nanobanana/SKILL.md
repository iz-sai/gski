---
name: gski nanobanana
description: Generate, edit, and understand images. Default skill for image generation and image editing tasks.
---

## How it works

`gski nanobanana` calls the Gemini API directly for image generation and editing. Output lands in `./output/`. Run from the directory where output should be saved, or pass `-o` / `--output-dir`.

Default model is `gemini-nano-banana-2.1` (`banana2.1`). Always use the default model `banana2.1`. Usage of older models (`flash3`, `flash2`, `pro`, `lite`, `gemini-3.1-flash-image`, `gemini-2.5-flash-image`, `gemini-3-pro-image`, `gemini-3.1-flash-lite-image`) is strictly prohibited. Do not pass `--model flash3`, `--model flash2`, `--model pro`, or request earlier generation models.

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
| `--model` | `banana2.1` | `banana2.1` | default: banana2.1 (`gemini-nano-banana-2.1`). Older models (flash3, flash2, pro, lite) are prohibited |
| `--aspect-ratio` | `1:1`,`1:4`,`1:8`,`2:3`,`3:2`,`3:4`,`4:1`,`4:3`,`4:5`,`5:4`,`8:1`,`9:16`,`16:9`,`21:9` | auto | output aspect ratio (auto matches input image or 1:1) |
| `--size` | `1K`,`2K`,`4K` | `1K` | output resolution: 1K, 2K, 4K |
| `--search`, `--web-search` | flag | off | enable Google Web Search grounding (real-time facts, news, weather) |
| `--image-search` | flag | off | enable Google Image Search grounding (visual reference retrieval) |
| `--thinking` | flag | off | use `medium` thinking level for complex compositions (default: `minimal`) |
| `--format` | `jpg`,`png`,`webp` | `jpg` | output image format (inferred from `-o` extension unless `--format` given) |
| `--output-dir` | path | `./output` | where to save output |
| `-o`, `--output` | path | none | exact output file path; overrides `--output-dir` and auto-naming |

## Prompting guide

### 1. Structure and visual details
- **Natural language over tags**: Avoid empty keywords ("8k, photorealistic, masterpiece"). Describe concrete scene attributes: subject, action/pose, environment, lighting, camera angle, and lens (e.g. `wide-angle shot`, `low perspective`, `50mm lens`, `soft natural light`).
- **Context and intent**: Explain the purpose of the image (`Create a logo for a high-end, minimalist skincare brand` beats `Create a logo`).
- **Step-by-step instructions**: For complex multi-element scenes, sequence the prompt (`First, create a background of... Then, in the foreground, add... Finally, place...`).
- **Semantic negative prompts**: Instead of saying `"no cars"`, describe the intended scene positively: `"an empty, deserted street with no signs of traffic"`.
- **Templates**:
  - Photorealistic: `A [type of shot] of [subject] in [setting]. [Lighting description]. Shot from [camera angle] with [lens type].`
  - Stylized/Sticker: `A [style] sticker/illustration of [subject] [doing action]. Bold clean outlines, simple cel-shading, vibrant colors, solid white background.`
  - Product mockup: `A high-resolution, studio-lit product photograph of [product] on [surface]. [Lighting setup, e.g. three-point softbox]. [Camera angle] showcasing [key detail].`
  - Minimalist / negative space: `A minimalist composition featuring a single [subject] in the [bottom-right/top-left] of the frame. Vast, empty [color] canvas creating significant negative space.`

### 2. Exact text rendering
- Put target wording in quotes: `"The Daily Grind"`.
- Descriptively specify typography, weight, color, and layout: `clean, bold, sans-serif font in black and white, centered`.
- Explicitly state exclusions if needed: `No other text, no extra logos`.
- For dense text (menus, infographics, articles), draft the exact text first and include it in the prompt.

### 3. Semantic inpainting and detail preservation
- Gemini does not use separate binary mask files. Use conversational semantic masking:
  `Using the provided image, change ONLY [specific element] to [new description]. Keep everything else in the image exactly the same, preserving original style, lighting, and composition.`
- To preserve critical details (faces, logos), describe them explicitly:
  `Take the first image of the woman with brown hair and blue eyes. Add the logo from the second image onto her t-shirt. Ensure the woman's face and features remain completely unchanged.`

### 4. Multi-image composition (up to 14 references)
- Supports up to 10 object fidelity references and up to 4 character consistency references.
- Refer to inputs by order or role:
  `Take the blue floral dress from the first image and have the woman from the second image wear it. Adjust lighting and shadows to match.`
- For character consistency across angles: feed the previous output and specify the new angle (`studio portrait of this character, in profile looking right, white background`).

### 5. Grounding with Search (`--search` and `--image-search`)
- `--search` (`--web-search`): Ground generation with Google Web Search for real-time factual data (weather forecasts, sports scores, recent news, charts).
- `--image-search`: Ground generation with Google Image Search to retrieve accurate visual references (specific animal/plant species, landmarks, objects). Can be combined with `--search`.
- Limitation: Search grounding does not support using real-world web images of people.

### 6. Thinking (`--thinking`)
- Default thinking level is `minimal`. Pass `--thinking` to use `medium` thinking for complex compositions, spatial layouts, or multi-step visual logic.

## Examples

```bash
# Generate
gski nanobanana "fox in snowy forest, watercolor style"
gski nanobanana "a modern logo for a coffee shop called 'The Daily Grind'"
gski nanobanana "isometric 3D miniature of Tokyo" --aspect-ratio 16:9 --thinking

# Edit
gski nanobanana "add sunglasses to the person" --image photo.png
gski nanobanana "change only the blue sofa to brown leather, keep everything else unchanged" --image room.png
gski nanobanana "restore to modern photo quality, full color" --image old_photo.jpg

# Multi-image
gski nanobanana "office group photo, funny faces" --image p1.png --image p2.png --image p3.png
gski nanobanana "put this logo on the product" --image product.png --image logo.png

# Search grounding (web vs image vs both)
gski nanobanana "infographic of today's weather in San Francisco" --search
gski nanobanana "3:2 wallpaper of a resplendent quetzal bird" --image-search --aspect-ratio 3:2
gski nanobanana "infographic of the Timareta butterfly habitat and appearance" --search --image-search

# Icons and assets
gski nanobanana "cute dog icon, colorful 3D style, white background" --aspect-ratio 1:1 -o dog_icon.png
gski nanobanana "seamless geometric triangle pattern, duotone" --aspect-ratio 1:1
```

## After generation

List `./output/` (or your `-o` / `--output-dir` path) to see generated files. Do not read image files.

DO NOT READ LARGE IMAGES OVER 5MB — this breaks opencode sessions.
