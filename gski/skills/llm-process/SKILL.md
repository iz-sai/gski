---
name: gski llm-process
description: Process files and data with Gemini — extract, transform, summarize, analyze
---

## Setup

Check: `which gski`
Install if missing: `pip install -e .` from `~/Documents/gski`
Requires `GEMINI_API_KEY` env var.

## How it works

`gski llm-process` sends files and a prompt to Gemini for processing. Accepts any combination of local files and stdin. PDFs and images are sent as binary parts with native vision; text files are inlined with filenames as headers.

Default model is `gemini-3.5-flash`.

## Commands

```bash
# Process a single file
gski llm-process "summarize this" -f report.pdf

# Multiple files
gski llm-process "compare these datasets" -f q1.csv -f q2.csv

# Pipe from stdin
cat data.json | gski llm-process "extract all email addresses"

# Combine stdin + files
cat prompt.txt | gski llm-process "follow these instructions" -f codebase.py

# System instruction
gski llm-process "clean this data" -f raw.csv --system "output as CSV, no markdown"

# JSON output
gski llm-process "extract names and dates" -f contract.pdf --json

# Use pro model
gski llm-process "deep analysis" -f paper.pdf --model pro

# Disable thinking for faster response
gski llm-process "list all functions" -f app.py --no-think
```

## Options

| Flag | Short | Values | Default | Notes |
|------|-------|--------|---------|-------|
| `--file` | `-f` | path | — | input file, repeatable |
| `--model` | `-m` | `flash`, `pro` | `flash` | model selection |
| `--system` | `-s` | text | — | system instruction |
| `--json` | — | flag | off | request JSON output |
| `--no-think` | — | flag | off | disable reasoning |

## File handling

- **PDF, images, audio, video**: sent as binary parts with correct MIME type (native multimodal)
- **Text files** (code, csv, md, txt, etc.): read as text, prefixed with filename
- **stdin**: read as text, labeled as `stdin`

## When to use

Use for any task that involves processing files with an LLM: summarization, extraction, transformation, analysis, code review, data cleaning, format conversion.
