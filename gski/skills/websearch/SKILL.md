---
name: gski websearch
description: Search the web using Google Search via Gemini grounding — current events, facts, documentation
---

## Setup

Check: `which gski`
Install if missing: `pip install -e .` from `~/Documents/gski`
Requires `GEMINI_API_KEY` env var.

## How it works

`gski websearch` sends a query to Gemini with Google Search grounding enabled. The model searches the web, synthesizes results, and returns text with inline citation references and resolved source URLs.

Vertex AI Search redirect URLs are automatically resolved to actual source URLs.

Default model is `gemini-3.5-flash`.

## Commands

```bash
# Basic search
gski websearch "who won the 2024 world series"

# Current events
gski websearch "latest news on AI regulation"

# Technical lookup
gski websearch "python 3.13 new features"

# Use flash-lite for cheaper/faster queries
gski websearch "weather in berlin" --model flash-lite

# Raw output (no citation formatting)
gski websearch "euro 2024 results" --raw
```

## Options

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--model` | `flash`, `flash-lite` | `flash` | model selection |
| `--raw` | flag | off | plain text without citation formatting |

## Output

Default output includes:
- Answer text with inline citation markers like `[1]`, `[2]`
- A `Sources:` section with numbered URLs and titles
- The search queries Gemini used

With `--raw`: just the plain response text, no citations or sources.

## When to use

Use when you need information beyond your training data: current events, recent releases, live data, verifying claims, documentation lookups.
