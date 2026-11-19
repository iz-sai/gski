---
name: gski ocq
description: Orchestrate opencode worker sessions - run parallel waves across model tiers, handle results, track state in a ledger
---

# ocq

`gski ocq` dispatches tasks to separate opencode sessions on the shared background service so Orchestrator (O) focuses on thinking, planning, and coordination while workers execute in parallel.

How O runs work with `ocq`:
- O plans the approach, gets go-ahead before the first run (unless already authorized in the prompt), and executes in bounded rounds: launch a wave of parallel tasks -> `wait` until the wave settles -> inspect structured results -> launch the next dependent wave if part of the plan -> stop and report results. Follow-up fixes go into an explicit next round, never ad-hoc mid-run spawning.
- Tasks use model/agent tiers matched to the job (all run at `high` automatically):
  - `worker` (`google/gemini-4-hydrogen`, default): implementation and tasks with a known procedure; executes strictly and reports blockers instead of investigating.
  - `builder` + `google/gemini-4-neon`: check, code review, audit, verification.
  - `builder` + `google/gemini-4-carbon`: architecture, design, hard trade-offs, open-ended investigation.
- Parallelism is the default: combine independent tasks in one wave — edits to disjoint files, `carbon` design on one area, `hydrogen` implementation on another, and `neon` review on finished code run together. 
    Separate into sequential waves (or merge into one task) only on real conflicts: editing the same files, reading files another task is modifying, output dependencies, shared mutable state (ports, DB, build artifacts), or heavy compute/benchmarks that contend for resources or skew timings.
- Meaningful tests, benchmarks, or a `neon` review/audit task are fine when requested or warranted; do not run paranoid syntax checks or boilerplate validation.

## State

```
.ocq/runs/<run>/
  brief.md           shared goal, context, conventions (optional; every worker reads it when present)
  run.json           run metadata and permissions (managed by ocq)
  ledger.jsonl       append-only task state: running | done | failed (managed by ocq)
  results/<id>.json  worker output: {"status": "done"|"failed", "artifact": ..., "note": ...}
```

## Commands

```bash
gski ocq spawn <run> "task"... [--file tasks.jsonl|-] [--agent worker|builder] [--model M] [--allow RULE]...
gski ocq wait <run> [--any] [--timeout 3600]
gski ocq ls [<run>] [--status S...]
gski ocq show <run> <id> [--chars 4000]
gski ocq send <run> <id> "text" [--queue] [--allow RULE]...
gski ocq send .. "text"
gski ocq abort <run> [<id>...]
```

- `spawn` creates `<run>` automatically if needed, assigns sequential IDs (`0001`, `0002`, ...), and starts all given tasks immediately in parallel.
- For mixed-tier waves in one call, pass `--file tasks.jsonl` (or `-` via stdin), one JSON object per line:
  `{"task": "...", "id"?: "0001", "agent"?: "worker"|"builder", "model"?: "google/gemini-4-neon", "allow"?: ["shell:ssh host *"]}`
- `/tmp/opencode/**` is allowed by default. Pass `--allow` only for extra user-approved permissions (`shell:git *`, `shell:ssh host *`, `external_directory:/path/**`). Workers cannot spawn subagents.

## Workflow and mechanics

1. Plan: read relevant inputs/docs; unless go-ahead was already given, send a concise plan (goal, wave/task breakdown, tiers, needed `--allow` rules) and wait for approval before first `spawn`.
2. Brief and tasks:
   - Write `.ocq/runs/<run>/brief.md` when multiple tasks share context, architecture, or conventions (skip for a single self-contained task). Workers have no O conversation context.
   - Give `worker` concrete procedure + inputs/outputs; give `builder` scope + constraints (state read-only explicitly for review/audit/design tasks). Stack back-to-back edits to the same file into one task.
3. Dispatch and wait:
   - Spawn the wave, then run `gski ocq wait <run> --timeout 3600` with `background: true`.
   - By default `wait` uses SSE (zero CPU) and returns once all running tasks in `<run>` finish; pass `--any` only when you need to react to the first completion while slower tasks keep running.
   - Always close a turn that starts background `wait` with a short one-liner (e.g. `wave 1 running, waiting`), never an empty response. On `timeout: N running`, restart background `wait` and reply `waiting`. Do not poll.
   - While waiting, the session stays free: check `ocq ls <run>` if asked for status.
4. Results and steering:
   - Workers write `results/<id>.json` and settle directly to `done` or `failed` (no manual done/fail step).
   - Read `ocq ls <run>` for artifacts and notes; call `ocq show <run> <id>` only when full reply/details are needed. Never read full worker transcripts.
   - To steer a running worker or ask a finished (`done`/`failed`) worker for a fix/follow-up in the same session context, run `ocq send <run> <id> "..."` (`--queue` waits for current turn; `done`/`failed` reopen to `running`). For a clean context, `spawn` a new task. Do not start a second `wait` if one is already active.
   - Workers can message O mid-run without stopping via `gski ocq send .. "..."`, delivered as `[ocq/<run>/<id>]`.
5. Permissions and stuck workers:
   - `NNNN denied <action>: <what>` means ocq auto-rejected an unapproved permission ask. Ask the user before granting `--allow`.
   - Workers running background shells stay `running` until shells exit and the final turn completes. For stuck outliers, inspect with `show`, then `abort <run> <id>` (kills bg shells -> `failed`).
6. Finish and resume:
   - When the round completes, stop and report outcomes, artifact paths, failures, cost, and a next-round proposal if fixes are needed.
   - A new O session resumes from files: `gski ocq ls [<run>]`, read `brief.md`, `gski ocq wait <run>`. If `server not reachable`, ask the user to run `opencode service start`.
