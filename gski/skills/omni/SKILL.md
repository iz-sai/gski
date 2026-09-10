---
name: gski omni
description: Generate, edit, interpolate, and extend videos with audio using Gemini Omni 1.1 Flash
---

# Gemini Omni

Use `gski omni` for video work. It uses `gemini-omni-1.1-flash` and keeps jobs stateful for follow-up edits and extensions. Generation waits by default; add `--async` only when background execution is wanted, then use `wait`.

Defaults: `9:16`, `720p`. Use `--aspect-ratio 16:9`, `--resolution 360p|1080p|4k`, or `--duration 3s..10s` to override. Higher resolutions are upscaled.

## Commands

```bash
gski omni generate "PROMPT" [--image FILE]... [--video FILE]... [--duration 3s-10s] [-o FILE]
gski omni edit JOB "ONE CHANGE" [--image FILE]... [--video FILE]... [--duration 3s-10s] [-o FILE]
gski omni extend JOB ["CONTINUATION"] [--image FILE]... [--video FILE]... [--duration 3s-10s] [-o FILE]

gski omni wait JOB [-o FILE]
gski omni status JOB
gski omni show JOB
gski omni list --all
gski omni rm JOB
```

Common options: `--aspect-ratio 9:16|16:9`, `--resolution 360p|720p|1080p|4k`, `--async`. Job IDs accept a unique prefix.

Examples:

```bash
gski omni generate "Single continuous shot of a marble racing along a chain-reaction track. No scene cuts. Metallic impacts and rolling sounds. No dialogue." -o marble.mp4
gski omni generate "<FIRST_FRAME> The camera slowly pushes in as her hair moves in the breeze." --image portrait.png
gski omni generate "<FIRST_FRAME> <LAST_FRAME> Smoothly transition from sunrise to a starry winter night." --image start.png --image end.png
gski omni generate "Extend this video: the camera pans across the mountains; the music continues." --video clip.mp4
gski omni edit JOB "Make the phone invisible. Keep everything else the same."
gski omni extend JOB "The scene continues; after 2s, cut to the same character outside."
```

Use `--task text_to_video|image_to_video|reference_to_video|edit|extend` only if a clear prompt does not select the intended mode; it constrains the model.

## Prompting

For generation, specify only what matters:

`scene + subject/action + camera + lighting/mood + audio + timing/text + exclusions`

- Omni makes multiple shots by default. For one shot say `Single continuous unbroken shot. No scene cuts.`
- Describe subject motion, camera motion, and environmental motion; avoid vague `make it move` prompts.
- State audio explicitly: dialogue, ambient sound, music, or `No dialogue. No extra sound effects.`
- Put unsupported negatives in the prompt: `Do not show...` or `No...`.
- Quote exact visible text. Time events naturally or with `[0-3s] ... [3-6s] ...`.
- For editing, request one simple change and end with `Keep everything else the same.`
- For extension, describe only what happens next and any audio transition. Time `0s` is the start of the new segment.

## Media roles

Files map to tags in flag order, indexed separately by type:

- `<FIRST_FRAME>` uses the first image as the opening frame.
- `<FIRST_FRAME> <LAST_FRAME>` interpolates between the first two images.
- `<IMAGE_REF_0>`, `<IMAGE_REF_1>` bind image references.
- `<VIDEO_REF_0>` binds a video reference rather than an edit source.

For ambiguous multi-file prompts, declare roles explicitly, for example:

```text
[# Sources <FIRST_FRAME>@Image1] [# References <IMAGE_REF_0>@Image2]
A woman <IMAGE_REF_0> walks toward the camera. Use Image1 as the starting frame; use Image2 only as a character reference.
```

## Constraints

- Uploaded videos for editing or extension must be at most 10 seconds; extension appends only at the end.
- Voice editing and audio-reference upload are unsupported. Audio in video references is ignored.
- Uploaded-video editing/extension is unavailable in the EEA, Switzerland, and UK; stateful edits of generated videos remain supported.
- System instructions, temperature, `top_p`, stop sequences, and a separate negative-prompt field are unsupported.

For uncommon media-role declarations, video-reference limits, regional restrictions, or raw API behavior, read `docs/gemini-omni.md` relative to the gski repository root.
