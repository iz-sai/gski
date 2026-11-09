---
name: gski omni
description: Generate, edit, interpolate, and extend videos with audio using Gemini Omni 1.2 Flash
---

# Gemini Omni

Use `gski omni` for video work. It uses `gemini-omni-1.2-flash` and keeps jobs stateful for follow-up edits and extensions. Generation waits by default; add `--async` only when background execution is wanted, then use `wait`.

Defaults: `9:16`, `720p`, `10s`. Use `--aspect-ratio 16:9`, `--resolution 360p|1080p|4k`, or `--duration 3s..15s` (`3s..10s` for first/last frame interpolation and per-turn extension) to override. Higher resolutions (`1080p`, `4k`) are upscaled.

## Commands

```bash
gski omni generate "PROMPT" [--image FILE]... [--video FILE]... [--duration 3s-15s] [-o FILE]
gski omni edit JOB "ONE CHANGE" [--image FILE]... [--duration 3s-15s] [-o FILE]
gski omni extend JOB ["CONTINUATION"] [--image FILE]... [--duration 3s-10s] [-o FILE]

gski omni wait JOB [-o FILE]
gski omni status JOB
gski omni show JOB
gski omni list --all
gski omni rm JOB
```

Common options: `--aspect-ratio 9:16|16:9`, `--resolution 360p|720p|1080p|4k`, `--async`. Job IDs accept a unique prefix.

## Backends

Default backend is Vertex AI (`vertex`) with a service account. Add `--backend api` on `generate` to use the Gemini API (`GEMINI_API_KEY`); the job remembers the backend, so `edit`, `extend`, `wait`, and `status` need no flag. Set `GSKI_OMNI_BACKEND=api` to override the default.

Vertex credentials are read from `~/.config/gski/gemcred.json` (or `GSKI_VERTEX_CREDENTIALS` / `GOOGLE_APPLICATION_CREDENTIALS`); project comes from the key file unless `GOOGLE_CLOUD_PROJECT` is set, location defaults to `global`. On Vertex, input videos are inlined instead of uploaded, so keep them small.

Examples:

```bash
gski omni generate "Single continuous shot of a marble racing along a chain-reaction track. No scene cuts. Metallic impacts and rolling sounds. No dialogue." --duration 15s -o marble.mp4
gski omni generate "Use this portrait as the starting frame; the camera slowly pushes in as her hair moves in the breeze." --image portrait.png
gski omni generate "A smooth cinematic transition from a lush green forest at sunrise to a snowy forest under a starry night sky." --image start.png --image end.png --duration 8s
gski omni generate "A cat playfully batting at a ball of yarn." --image cat.png --image yarn.png
gski omni generate "Extend this video: have the character shown in the reference image enter the scene and wave." --video clip.mp4 --image character.png
gski omni edit JOB "Make the phone invisible. Keep everything else the same."
gski omni extend JOB "The scene continues; after 2s, cut to the same character outside."
```

Use `--task text_to_video|image_to_video|reference_to_video|edit|extend` only as a fallback if a clear natural-language prompt does not select the intended mode; setting `task` adds strict constraints on media inputs.

## Prompting

For generation, specify only what matters:

`scene + subject/action + camera + lighting/mood + audio + timing/text + exclusions`

- Omni makes multiple shots by default. For one shot say `In a single continuous shot. No scene cuts.`
- Describe subject motion, camera motion, and environmental motion; avoid vague `make it move` prompts.
- State audio explicitly: dialogue, ambient sound, music, or `No dialogue. No extra sound effects.`
- Put unsupported negatives in the prompt: `Do not show...` or `No...`.
- Quote exact visible text (including background signs/plates). Time events naturally or with `[0-5s] ... [5-10s] ... [10-15s] ...`.
- For editing, request one simple change and end with `Keep everything else the same.`
- For extension, describe only what happens next and any audio transition. Time `0s` is the start of the extended segment.

## Media inputs and roles

Describe how each image or video should be used in natural language. Do NOT use deprecated control tags (`<FIRST_FRAME>`, `<LAST_FRAME>`, `<IMAGE_REF_0>`, `<VIDEO_REF_0>`, or `[# Sources ...]`).

- **Image to video (1 image):** pass `--image FILE` and describe the motion or how to use the image (e.g. starting frame or movement guide). Supports `3s`–`15s`.
- **First and last frame interpolation (2 images):** pass two `--image` flags (first frame, then last frame) and describe the transition. Supports `3s`–`10s` only (`>10s` errors).
- **Subject/character reference images:** pass up to 6 `--image` flags (up to 3 images per character for up to 2 characters) across all durations. Supported in `generate`, `edit`, and `extend`.
- **Reference videos:** visual likeness only (audio is ignored), supported only when generating a new video (not in `edit` or `extend`). `3s`–`10s` outputs allow up to 3 reference videos (up to 3s each); `11s`–`15s` outputs allow 1 reference video (up to 3s).

## Constraints

- Uploaded and model-generated input videos for editing must be 15 seconds or less.
- Extension uses the final 10 seconds of the input video as context (re-mention or pass a reference image for anything that only appeared earlier) and appends 3 to 10 seconds per turn (10s default) at the end, up to 30 seconds total video length.
- Cannot extend an uploaded video where someone is talking to add dialogue (silent characters or multi-turn extension via `previous_interaction_id` is supported).
- Voice editing and audio input/reference upload are unsupported.
- Uploaded-video editing/extension is unavailable in the EEA, Switzerland, and UK; stateful edits/extensions of model-generated videos remain supported.
- System instructions, temperature, `top_p`, stop sequences, and a separate negative-prompt field are unsupported.

For raw REST/URI delivery behavior or additional prompt examples, read `docs/gemini-omni.md` relative to the gski repository root.
