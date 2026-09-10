---
name: gski deepresearch
description: Gemini Deep Research agent — async multi-step research with planning, citations, and long-form reports
---

## How it works

Deep Research is an autonomous agent that plans, searches, reads, and synthesizes multi-step research tasks. Tasks run in the background on Google's infrastructure and typically take several minutes. This skill wraps the Interactions API with local job tracking so tasks survive disconnects.

Local state lives in `$XDG_STATE_HOME/gski/deepresearch/` (defaults to `~/.local/state/gski/deepresearch/`). Each job is a JSON file keyed by a short `job_id` (8 hex chars). Reports are saved alongside as `<job_id>.md`.

Jobs have a `state`: `running`, `planning`, `completed`, `failed`.

## Commands

```bash
# Fire-and-forget: start research, return immediately
gski deepresearch start "compare EV battery chemistries in 2025"

# Start and wait for it to finish (blocks)
gski deepresearch start "history of Google TPUs" --wait

# Resume polling (e.g. after terminal closed)
gski deepresearch wait <job_id>

# List active jobs
gski deepresearch list
gski deepresearch list --all           # include completed

# Quick status check (no polling)
gski deepresearch status <job_id>

# Print saved report
gski deepresearch show <job_id>

# Planning mode — agent proposes a plan first
gski deepresearch start "research cloud GPU landscape" --plan
gski deepresearch refine <job_id> "focus on pricing, skip history"
gski deepresearch approve <job_id>

# With input documents (local or URL)
gski deepresearch start "summarize and expand on this" --file paper.pdf
gski deepresearch start "analyze this image" --file chart.png

# Use the max model for deeper analysis
gski deepresearch start "deep due diligence on X" --max

# Save report to specific path (always also saved in state dir)
gski deepresearch start "query" --output report.md

# Clean up
gski deepresearch rm <job_id>
```

Job IDs can be given by any unique prefix (e.g. `a3f2` matches `a3f2c9b1`).

## Options reference

### `start`

| Flag | Default | Notes |
|------|---------|-------|
| `--file`, `-f` | — | input file path or URL (PDF/image), repeatable |
| `--max` | off | use `deep-research-max-preview-04-2026` (more comprehensive, more expensive) |
| `--plan` | off | collaborative planning mode — returns plan instead of executing |
| `--output`, `-o` | — | write report to path (always also saved in state dir) |
| `--wait` | off | block until completion instead of returning immediately |

### `approve`

| Flag | Default | Notes |
|------|---------|-------|
| `--message`, `-m` | "Plan looks good, proceed." | approval message to the agent |
| `--output`, `-o` | — | write report to path |
| `--wait` | off | block until completion after approval |

## Planning workflow

1. `start --plan` returns a proposed plan.
2. Any number of `refine <id> "feedback"` iterations — each creates a new interaction chained off the previous one.
3. `approve <id>` executes the final plan and produces the report.

Local state tracks the interaction chain: every plan/refine/execute step is recorded in the job's `interactions` array. Only the latest interaction is polled.

## Models & cost

| Model | Typical cost | Use for |
|-------|--------------|---------|
| `deep-research-preview-04-2026` (default) | ~$1–3 | most research tasks |
| `deep-research-max-preview-04-2026` (`--max`) | ~$3–7 | due diligence, comprehensive competitive landscapes |

## Limits

- Max research time: 60 minutes (most tasks finish within 20).
- **Known upstream bug:** long-running jobs can permanently break mid-run — `status`/`wait` start returning `400 invalid_request` ("Request contains an invalid argument") and the report becomes unrecoverable. This is a backend flakiness issue (sandbox timeout / interaction-id propagation failure), not a local bug; see the [Google AI dev forum thread](https://discuss.ai.google.dev/t/post-v1beta-interactions-succeeds-but-get-v1beta-interactions-id-returns-403-permission-denied-for-deep-research/129792). Short jobs are unaffected. Nothing local can recover a broken job — restart it.
- Interactions API is in preview; expect occasional schema changes.
- Local files are uploaded via `client.files.upload()` then referenced by URI.
- Streaming thought summaries are not surfaced by this skill; only status transitions and the final report.

## When to use

- Multi-step analyst workloads: market research, literature reviews, competitive landscaping, due diligence.
- Anything where you want a long, cited, structured report rather than a chat answer.
- Not for low-latency queries — use `gski websearch` for quick lookups instead.
