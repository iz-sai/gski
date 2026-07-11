---
name: gski tgscope
description: Search, read, and summarize Telegram chat/channel JSON exports — find posts, read full messages, get overviews, and produce a structured digest of a whole channel
---

## Setup

Check: `which gski`
Install if missing: `pip install -e .` from the gski repo.

## How it works

Telegram Desktop exports a channel or chat as a single large `result.json` (inside a `ChatExport_*` folder). The raw file is awkward to read directly — **do not read it raw**. `gski tgscope` wraps it so you can search and read messages without loading the whole thing into context.

Pass either the export **directory** (it finds `result.json`) or the `result.json` path directly. Three actions:

- `info` — overview of the export
- `search` — find messages matching text or regex
- `show` — print full messages by id (with optional neighbor context)

Output is human-readable text by default; add `--json` for machine-readable output.

## Commands

```bash
EXPORT="/path/to/ChatExport_2026-06-26"

# Overview: channel name, date range, message count, media/reaction totals
gski tgscope info "$EXPORT"

# Search messages (case-insensitive substring by default)
gski tgscope search "$EXPORT" "приседания"

# Regex search
gski tgscope search "$EXPORT" "FTP\s*\d+" --regex

# Filter by date and engagement; cap results
gski tgscope search "$EXPORT" "питание" --since 2024-01-01 --until 2024-12-31 --min-reactions 50 --limit 20

# Only a given media kind (photo, video_file, voice_message, poll, file, ...)
gski tgscope search "$EXPORT" "техника" --media voice_message

# Read full messages by id (single, list, or range)
gski tgscope show "$EXPORT" 701
gski tgscope show "$EXPORT" 12,15,18
gski tgscope show "$EXPORT" 100-110

# Read a message with 2 neighbors before/after for context (threads)
gski tgscope show "$EXPORT" 701 --context 2

# JSON output for piping
gski tgscope search "$EXPORT" "вело" --json | jq 'select(.media == "video_file")'
gski tgscope show "$EXPORT" 100-110 --json
```

## Options

### search
| Flag | Default | Notes |
|------|---------|-------|
| `query` | required | text (substring) or regex |
| `--regex` | off | treat query as a regex |
| `--case-sensitive` | off | default is case-insensitive |
| `--since YYYY-MM-DD` | — | only messages on/after |
| `--until YYYY-MM-DD` | — | only messages on/before |
| `--media KIND` | — | photo, video_file, voice_message, video_message, audio_file, file, poll |
| `--min-reactions N` | 0 | minimum total reaction count |
| `--limit N` | all | max results |
| `--width N` | 200 | snippet width in chars |
| `--json` | off | JSONL output |

Search looks through message text, poll questions, and `forwarded_from`.

### show
| Flag | Default | Notes |
|------|---------|-------|
| `ids` | required | `12`, `12,15`, or range `10-20` (space-separated args allowed) |
| `--context N` | 0 | also print N neighbor messages before/after each id |
| `--json` | off | raw JSON objects |

## Output

`search` prints one block per hit:
```
#701  2023-11-16 06:39  [voice_message]
    …snippet around the match…
```
Match count goes to stderr, so stdout stays clean for piping.

`show` prints full text plus metadata: date, author, media kind/size/duration, forwarded source, reply target, and poll answers with vote counts.

## Research workflow

```bash
EXPORT="/path/to/ChatExport_..."

# 1. Get oriented
gski tgscope info "$EXPORT"

# 2. Find candidate posts on a topic, note the ids
gski tgscope search "$EXPORT" "your topic" --min-reactions 20

# 3. Read the most relevant ones in full
gski tgscope show "$EXPORT" 701,820,933

# 4. For threads/discussions, pull surrounding context
gski tgscope show "$EXPORT" 820 --context 3
```

## Summarize a whole channel

When the user wants to understand what a channel is about ("summarize with
tgscope", "what is this channel", "digest this export"), dump every post to a
raw text file and run `gski llm-process` over it. No need to ask for steps —
run this chain end to end:

```bash
EXPORT="/path/to/ChatExport_..."   # dir or result.json

# 1. Orient + confirm it parses
gski tgscope info "$EXPORT"

# 2. Find the id range (ids may have gaps; show handles missing ids gracefully)
JSON="$EXPORT"; [ -d "$EXPORT" ] && JSON="$EXPORT/result.json"
RANGE=$(python3 -c "import json,sys; m=json.load(open(sys.argv[1]))['messages']; i=[x['id'] for x in m]; print(f'{min(i)}-{max(i)}')" "$JSON")

# 3. Dump all posts to raw text (keep it out of context; write to a file)
gski tgscope show "$EXPORT" "$RANGE" > posts_raw.txt

# 4. Structured summary via llm-process (use --model pro for long channels).
#    Match the summary language to the channel's language.
gski llm-process "This is a raw dump of Telegram channel posts. Produce a
structured summary covering: 1) overall theme and how the author positions
themselves 2) main recurring topics/rubrics with rough frequency 3) key ideas
and opinions 4) tone and style toward the audience 5) how content evolves over
time 6) target audience. Ignore '(not found)' lines — technical noise." \
  -f posts_raw.txt --model pro
```

Notes on this flow:
- `show` prints `(not found)` for gaps/service-only ids — harmless; the prompt
  tells the model to ignore them.
- For very large channels the raw dump may be big; `--model pro` handles long
  context better than flash.
- Write the dump to a file and pass it with `-f`; do not read `posts_raw.txt`
  back into the conversation.

## Notes

- Media binaries are usually NOT in the export (Telegram includes only metadata: sizes, dimensions, durations, mime types) unless the user enabled media download.
- Channel posts almost always come `from` the channel itself; group chats will have varied authors.
- Message `id` values are stable within an export, so ids from `search` feed directly into `show`.
- Service messages (channel creation, title edits, pins) appear with a `[service: ...]` tag.
