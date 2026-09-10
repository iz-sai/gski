---
name: gski youtube-scope
description: Extract data from YouTube — metadata, comments, transcripts via yt-dlp
---

## How it works

`gski youtube-scope` wraps yt-dlp to extract structured data from YouTube. Give it a target — a video URL, channel URL, playlist URL, search query, or a file of URLs — and it returns JSONL (one JSON object per video) to stdout. Progress goes to stderr.

The target type is auto-detected:
- Starts with `http` → URL (video, channel, or playlist — yt-dlp figures it out)
- Existing file path → reads URLs from it, one per line
- Anything else → YouTube search query

## Commands

```bash
# Search YouTube, get metadata for top 50 results
gski youtube-scope "how I use notion for" --limit 50

# Single video — metadata only
gski youtube-scope "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Single video — with comments and transcript
gski youtube-scope "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --comments --transcript

# All videos from a channel (limit to 20)
gski youtube-scope "https://www.youtube.com/@channelname" --limit 20

# Channel with comments
gski youtube-scope "https://www.youtube.com/@channelname" --limit 10 --comments

# File of URLs — pull comments and transcripts
gski youtube-scope urls.txt --comments --transcript

# With resumability — skip already-processed videos on re-run
gski youtube-scope urls.txt --comments --archive done.txt

# Save output to file
gski youtube-scope "how I use google sheets for" --limit 30 > scan.jsonl

# Pipe to jq for filtering
gski youtube-scope "my workflow for" --limit 50 | jq 'select(.comment_count > 100)'
```

## Options

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `target` | positional, required | — | URL, search query, or file path (auto-detected) |
| `--comments` | flag | off | include comments in output |
| `--transcript` | flag | off | include transcript/subtitles |
| `--limit N` | integer | 20 for search, unlimited for URLs | max videos to process |
| `--archive FILE` | path | none | track processed IDs for resumability |

## Output

JSONL to stdout — one JSON object per line, one per video. Each object always contains:

```json
{
  "id": "video_id",
  "url": "https://www.youtube.com/watch?v=...",
  "title": "...",
  "channel": "...",
  "channel_url": "...",
  "upload_date": "20240115",
  "duration": 623,
  "view_count": 15000,
  "like_count": 450,
  "comment_count": 89,
  "description": "...",
  "tags": ["..."],
  "categories": ["..."]
}
```

With `--comments`, adds `"comments": [{"author": "...", "text": "...", "likes": 5, "is_reply": false}, ...]`

With `--transcript`, adds `"transcript": "full transcript text..."`

Progress and status messages go to stderr, so stdout is always clean JSONL for piping.

## Workflow: Job Problem Search

A practical workflow for finding product opportunities:

```bash
# 1. Wide scan — search for workaround/DIY solution videos
gski youtube-scope "how I use notion for" --limit 50 > scan.jsonl
gski youtube-scope "my google sheets system for" --limit 50 >> scan.jsonl
gski youtube-scope "my workflow for managing" --limit 50 >> scan.jsonl

# 2. Filter by engagement density (comment/view ratio)
jq 'select(.view_count > 0 and (.comment_count / .view_count) > 0.03)' scan.jsonl > hits.jsonl

# 3. Deep dive — pull comments and transcripts for high-signal videos
jq -r '.url' hits.jsonl > urls.txt
gski youtube-scope urls.txt --comments --transcript --archive done.txt > data.jsonl

# 4. Feed into LLM for problem extraction (external step)
```

## Notes

- Metadata-only searches are fast (flat playlist mode). Adding `--comments` or `--transcript` is much slower — one yt-dlp call per video.
- `--archive` only works when passing a **file of URLs** or a channel/playlist as target — yt-dlp checks the archive before processing each video in the batch. It does **not** work when calling gski in a loop with one URL per call, because each invocation is independent. For loop-based resumability, maintain the archive yourself: check before calling, append the video ID after success.
- yt-dlp handles rate limiting internally. For large batches, expect some throttling.
- Transcripts use YouTube's auto-captions if manual subtitles aren't available. English is preferred, falls back to first available language.
- Output is streamed — each video is printed as soon as it's processed. Safe to interrupt.
