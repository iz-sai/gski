---
name: gski gptimage2
description: Generate and edit images with OpenAI GPT Image (gpt-image-2.5-flare). Use ONLY when explicitly asked to use GPT Image or OpenAI for image generation.
---

## How it works

`gski gptimage2` calls the OpenAI Image API directly. Output lands in `./output/`. Run from the directory where output should be saved.

Default model is `gpt-image-2.5-flare`.
- `gpt-image-2.5-flare` (default): Fast, high-quality everyday image generation and editing. Always use Flare by default.
- `gpt-image-2.5-sunburst`: Only use when the user explicitly asks for Sunburst.
- Earlier models: `gpt-image-2`, `gpt-image-1.5`, `gpt-image-1`, `gpt-image-1-mini`.

Quality:
- Default is `high` (strong balance of quality and speed).
- Do NOT use `max` quality unless the user explicitly requests it (high latency and token cost).
- User can explicitly request any quality setting: `low` (fast drafts), `medium`, `high` (default), `xhigh`, `max`, or `auto`.

For Gemini-based image generation, use `gski nanobanana` instead.

## Commands

```bash
gski gptimage2 "prompt"                                              # text-to-image (default: gpt-image-2.5-flare, quality high)
gski gptimage2 "instruction" --image file.png                        # edit existing image
gski gptimage2 "prompt" --image a.png --image b.png                  # multi-image composition / reference images
gski gptimage2 "replace pool with lawn" --image room.png --mask mask.png  # masked edit
gski gptimage2 "bakery logo" --background transparent                # transparent background (PNG)
```

## Options

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--image FILE` | repeatable | none | input image(s); triggers edit mode |
| `--mask FILE` | path | none | masked edit; applies to first `--image` |
| `--model` | `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst`, `gpt-image-2`, `gpt-image-1.5`, `gpt-image-1`, `gpt-image-1-mini` | `gpt-image-2.5-flare` | Flare = default; Sunburst = only when user explicitly asks |
| `--size` | `auto`, `1024x1024`, `1536x1024`, `1024x1536`, `2048x2048`, `2048x1152`, `3840x2160`, `2160x3840`, or any `WxH` | `auto` | edges multiples of 16, max edge 3840, ratio ≤ 3:1, pixels 655,360–8,294,400 (>2560x1440 experimental) |
| `--quality` | `auto`, `low`, `medium`, `high`, `xhigh`, `max` | `high` | Default is `high`. Do NOT use `max` unless explicitly asked. User can explicitly set quality. |
| `--format` | `jpg`, `png`, `webp` | `jpg` | auto-switches to `png` if `--background transparent` is set |
| `--compression` | `0-100` | none | jpg/webp only |
| `--background` | `auto`, `opaque`, `transparent` | `auto` | `transparent` requires `png` or `webp` |
| `-n N` | integer | `1` | number of images |
| `--output-dir` | path | `./output` | directory to save generated images |
| `-o`, `--output` | path | none | exact output file path; overrides `--output-dir` and auto-naming |

## Model selection

- `gpt-image-2.5-flare` (default): The default model for all image generation and editing tasks. Always use Flare unless the user explicitly requests another model. Fast generation, strong instruction following, sharp text rendering, and transparent background support.
- `gpt-image-2.5-sunburst` (`--model gpt-image-2.5-sunburst`): ONLY use when the user explicitly calls for Sunburst. Do not switch to Sunburst proactively.

## Prompting guide

### 1. Structure and visual details
- **Define the deliverable**: Name the subject, medium (photograph, 3D render, diagram, slide, logo), composition, aspect ratio, and framing.
- **For complex requests**: Organize prompt into sections: Scene, Subject, Details, and Constraints.
- **Describe visible details, not hype words**: Avoid empty buzzwords like "hyperrealistic 8K photorealistic masterpiece". Instead, describe materials, textures, lighting, lens/camera cues (e.g., "35mm film photograph, 50mm lens, soft coastal daylight, shallow depth of field, subtle film grain, natural skin texture, unposed").
- **People and actions**: Specify framing ("full body visible, feet included"), relative scale, gaze direction ("looking down at the open book"), and natural interactions with objects.

### 2. Exact text rendering
- Put required wording in quotes (e.g., `"Yours to Create"`).
- Specify placement, typography (e.g., bold sans-serif), and color.
- Add constraints: "Render the text exactly once, clearly and legibly. No extra text, no watermarks, no unrelated logos."
- Default `high` quality ensures clean, legible typography.

### 3. Productivity visuals, diagrams, and slides
- Treat the prompt like an artifact specification rather than an illustration request.
- Provide exact titles, bullet points, data numbers, and footnotes in the prompt.
- Specify clean layouts: minimal sans-serif typography, clean white background, clear data hierarchy, no decorative clutter or stock-photo tropes.

### 4. Image editing and subject preservation
- **Separate changes from constraints**: Say "Change ONLY X" and list everything to keep identical ("Preserve her exact likeness, face, skin tone, body shape, pose, expression, lighting, shadows, and camera angle").
- **Multi-image composition**: Assign numbered roles to references:
  `--image background.png --image person.png`
  Prompt: "Place the person from image 2 into the setting of image 1 next to the window. Match lighting, contact shadows, and scale. Keep all other aspects unchanged."
- **Object replacement / removal**:
  - Replacement: "In this room photo, replace ONLY the white chairs with wooden chairs. Preserve camera angle, room lighting, floor shadows, and surrounding objects."
  - Removal: "Remove the flower from the man's hand. Do not change anything else."
- **Sketch-to-render**: "Turn this drawing into a photorealistic image. Preserve the exact layout, proportions, and perspective. Choose realistic materials and lighting consistent with the sketch intent. Do not add new elements or text."
- **Iterative refinement across turns**: Refine one change at a time. Pass the previous output as the next edit input and restate preserved details so the scene does not drift.

### 5. Transparent backgrounds and cutouts
- Use `--background transparent` (and ensure format is `png` or `webp`).
- Prompt: "Extract the product from the input image and isolate it on a fully transparent background. Centered product, crisp silhouette, no halos/fringing, clean alpha transparency. Do not add solid backdrop, scenery, checkerboard, or watermark."

## Mask requirements

- Image and mask must have identical dimensions and format (<50MB).
- Mask must have an alpha channel: transparent pixels (alpha = 0) represent the edit area; opaque pixels are preserved.
- Masking with GPT Image is prompt-guided; always accompany the mask with a prompt describing what to render in the masked region.

## Examples

```bash
# General generation (default model gpt-image-2.5-flare, default quality high)
gski gptimage2 "candid 35mm film photograph of an elderly sailor repairing a fishing net on a boat deck, soft coastal morning daylight, natural skin texture"

# Exact text rendering in an ad
gski gptimage2 'streetwear campaign ad of friends on a city street with tagline "Yours to Create" rendered exactly once in bold clean sans-serif typography, no extra text'

# Pitch-deck slide artifact
gski gptimage2 'pitch-deck slide titled "Market Opportunity", clean minimal startup deck layout on white background, TAM $42B, SAM $8.7B, SOM $340M diagram, legible typography' --size 1536x864

# Fast low-quality draft
gski gptimage2 "quick concept sketch of a robotic hummingbird" --quality low

# Maximum precision / demanding quality with Sunburst (when Flare is not enough)
gski gptimage2 "intricate architectural cross-section of a gothic cathedral, ultra-fine stonework details" --model gpt-image-2.5-sunburst

# Transparent logo / icon
gski gptimage2 "minimal flat vector bakery logo of a wheat stalk forming an infinity symbol, clean alpha edges" --background transparent

# Edit: preserve identity, change clothes
gski gptimage2 "Replace only the clothing with a dark wool coat. Preserve exact face, expression, pose, lighting, and background." --image portrait.png

# Edit: compositing multiple images
gski gptimage2 "Place the dog from image 2 sitting beside the person in image 1. Match lighting and shadows. Do not change anything else." \
  --image scene.png --image dog.png

# Edit: inpainting with mask
gski gptimage2 "a sunlit indoor lounge with a flamingo swimming in the pool" \
  --image room.png --mask pool_mask.png
```

## After generation

List `./output/` to see generated files. Do not read image files.

DO NOT READ LARGE IMAGES OVER 5MB — this breaks opencode sessions.
