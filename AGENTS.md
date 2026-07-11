# gski

Pip-installable Python package. Bundles skill scripts (CLI tools) and their OpenCode SKILL.md files.

## Structure

```
gski/
├── pyproject.toml
└── gski/
    ├── cli.py              # entry point: gski <command>
    ├── deepresearch.py     # gski deepresearch — Gemini Deep Research agent (async jobs)
    ├── gptimage2.py        # gski gptimage2 — OpenAI GPT Image gen/edit
    ├── llm_process.py      # gski llm-process — process files/data with Gemini
    ├── nanobanana.py       # gski nanobanana — Gemini image gen/edit
    ├── nanoscope.py        # gski nanoscope — Gemini image understanding
    ├── omni.py             # gski omni — Gemini Omni Flash video gen/edit (stateful jobs)
    ├── omni_lib/           # omni job state, interactions/video plumbing
    ├── tgscope.py          # gski tgscope — search/read Telegram chat JSON exports
    ├── websearch.py        # gski websearch — web search via Gemini grounding
    ├── youtube_scope.py    # gski youtube-scope — YouTube data extraction via yt-dlp
    ├── setup.py            # gski setup <dir> — copy SKILL.md files
    └── skills/
        ├── deepresearch/
        │   └── SKILL.md
        ├── gptimage2/
        │   └── SKILL.md
        ├── llm-process/
        │   └── SKILL.md
        ├── nanobanana/
        │   └── SKILL.md
        ├── nanoscope/
        │   └── SKILL.md
        ├── omni/
        │   └── SKILL.md
        ├── tgscope/
        │   └── SKILL.md
        ├── websearch/
        │   └── SKILL.md
        └── youtube-scope/
            └── SKILL.md
```

## CLI

```
gski gptimage2 "prompt" [--image FILE]... [--mask FILE] [--model gpt-image-2|...] [--size WxH|auto] [--quality auto|low|medium|high] [--format jpg|png|webp] [--compression N] [--background auto|opaque] [-n N] [--output-dir DIR]
gski llm-process "prompt" --file FILE [--file FILE]... [--model flash|pro] [--system TEXT] [--json] [--no-think]
gski nanobanana "prompt" [--image FILE]... [--model flash|pro] [--aspect-ratio RATIO] [--size 1K|2K|4K] [--search] [--output-dir DIR]
gski nanoscope "prompt" --image FILE [--url URL]... [--model flash|pro] [--detect] [--segment] [--output-dir DIR]
gski omni generate "prompt" [--image FILE]... [--video FILE] [--aspect-ratio 16:9|9:16] [--task text_to_video|image_to_video|reference_to_video|edit] [--output FILE] [--wait]
gski omni edit <job-id> "prompt" [--aspect-ratio 16:9|9:16] [--output FILE] [--wait]
gski omni list|status|wait|show|rm ...
gski tgscope info|search|show <export-dir-or-result.json> ...
  search "query" [--regex] [--case-sensitive] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--media KIND] [--min-reactions N] [--limit N] [--width N] [--json]
  show <ids> [--context N] [--json]   # ids: 12 | 12,15 | 10-20
gski websearch "query" [--model flash|flash-lite] [--raw]
gski youtube-scope <target> [--comments] [--transcript] [--limit N] [--archive FILE] [--audio] [--video] [--res N] [--audio-quality N] [--output-dir DIR] [--update]
gski deepresearch start "query" [--file F]... [--max] [--plan] [--output FILE] [--wait]
gski deepresearch list|status|wait|show|refine|approve|rm ...
gski setup <target-dir>
```

## Adding a new skill

1. Create `gski/<skillname>.py` with `register(subparsers)` and `run(args)`
2. Import and call `register()` in `cli.py`
3. Add `gski/skills/<skillname>/SKILL.md`

## Dependencies

- `google-genai` — Gemini API SDK
- `openai` — OpenAI API SDK (for gptimage2)
- `Pillow` — image handling
- Requires `GEMINI_API_KEY` env var
- Requires `OPENAI_API_KEY` env var for gptimage2
- Requires `yt-dlp` for youtube-scope

## Install

```
pip install -e .
```
