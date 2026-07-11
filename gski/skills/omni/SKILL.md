---
name: gski omni
description: Gemini Omni Flash — stateful video generation and editing from text, images, or video
---

## Setup

Check: `which gski`
Install if missing: `pip install -e .` from `~/Documents/gski`
Requires `GEMINI_API_KEY` env var.

## How it works

Gemini Omni Flash (`gemini-omni-flash-preview`) generates video with audio from text, images, or a source video, and edits it conversationally. This skill wraps the Interactions API with local job tracking so multi-turn edits survive disconnects.

Every job is stateful. A one-shot is just a job you generate and never edit — use `generate --wait` and take the video. To iterate, `edit <job-id>` chains off the previous result via `previous_interaction_id`, so the model keeps everything you did not mention.

Local state lives in `$XDG_STATE_HOME/gski/omni/` (defaults to `~/.local/state/gski/omni/`). Each job is `<job_id>.json`; the current video is saved alongside as `<job_id>.mp4`. Job IDs accept any unique prefix.

Jobs have a `state`: `running`, `completed`, `failed`.

## Commands

```bash
# One-shot: generate and wait for the video
gski omni generate "a marble rolling on a chain-reaction track, continuous smooth shot" --wait

# Fire-and-forget: returns a job id immediately
gski omni generate "a futuristic city with neon lights, cyberpunk" --aspect-ratio 9:16
gski omni wait <job_id>                          # resume polling later

# Image to video (reference / first frame)
gski omni generate "turn this into realistic footage, drawing as motion guide only" --image fish.png --wait
gski omni generate "the cat plays with the yarn" --image cat.png --image yarn.png --wait

# Edit your own video
gski omni generate "make the mirror ripple like liquid when touched" --video clip.mp4 --wait

# Stateful editing — chains off the previous result
gski omni generate "a woman playing violin outdoors" --wait
gski omni edit <job_id> "make the violin invisible. Keep everything else the same." --wait

# Tracking
gski omni list                                   # active jobs
gski omni list --all                             # include completed
gski omni status <job_id>                         # no polling
gski omni show <job_id>                           # print saved video path
gski omni rm <job_id>                             # remove from tracking

# Save a copy to a specific path (always also kept in state dir)
gski omni generate "a beautiful sunset over the ocean" --wait -o sunset.mp4
```

## Options

### `generate`

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--image FILE` | repeatable | none | reference / first-frame image |
| `--video FILE` | path | none | source video to edit (uploaded via Files API) |
| `--aspect-ratio` | `16:9`, `9:16` | `16:9` | portrait or landscape |
| `--task` | `text_to_video`, `image_to_video`, `reference_to_video`, `edit` | inferred | explicit task hint |
| `--output`, `-o` | path | — | also write video here |
| `--wait` | flag | off | block until the video is ready |

### `edit`

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--aspect-ratio` | `16:9`, `9:16` | inherit | output aspect ratio |
| `--output`, `-o` | path | — | also write video here |
| `--wait` | flag | off | block until the video is ready |

## Prompting guide

Omni tries to build a multi-shot narrative by default. Steer it with the prompt.

- **Single scene:** add "In a single unbroken shot", "No scene cuts".
- **Remove clutter:** "No dialogue", "No extra sound effects".
- **Audio:** describe it — "Include calm background music", "high-energy techno beat". Otherwise the model picks its own track.
- **Timing:** natural language works — "After 3 seconds a woman enters". Or timecodes:
  ```
  [0-3s] A person is walking
  [3-6s] They stop and turn around
  [6-10s] They start running
  ```
- **Text on screen:** quote it exactly — a sign that says "Omni Flash".

### Editing prompts

Keep edits simple; overly descriptive edits cause unintended changes. Add "Keep everything else the same" to preserve the rest.

- Good: `Add a cat that jumps onto his lap, he begins to pet it. Keep everything else the same.`
- Good: `Make the phone invisible. Keep everything else the same.`

### Image-role tags

Bind uploaded images to roles inside the prompt:

- `<FIRST_FRAME>` — use the image as the starting frame: `<FIRST_FRAME> a woman is walking`
- `<IMAGE_REF_N>` — use as reference (indexed from 0): `in the style of <IMAGE_REF_0> a woman <IMAGE_REF_1> is walking`

Images map to tags in the order passed via `--image`.

## Limits

- Preview API; schema can change. Negatives, temperature, top_p, system instructions are not supported — put negatives in the prompt ("Do not do X").
- Video-to-video editing is unavailable in the EEA, Switzerland, and the UK (editing model-generated videos still works).
- No audio-reference upload, no voice editing, no video extension/interpolation, no multi-video reasoning, no YouTube sources.
- All output carries invisible SynthID watermarking. English is fully supported.

## When to use

- Short generated clips with audio, product shots brought to life, iterative visual edits.
- Not for image-only work — use `gski nanobanana` (generate/edit) or `gski nanoscope` (understand).
