---
name: gski ocq
description: Orchestrate opencode worker sessions - split work into tasks, dispatch, handle reports, track state in a ledger
---

# ocq

`gski ocq` runs tasks in separate opencode worker sessions on the shared
opencode background service (auto-started; `OCQ_URL`/`OCQ_PASSWORD` target
another server, `gski ocq serve` runs a separate one). You are the orchestrator:
you plan, dispatch, read reports, and decide. Never implement features or do
real tasks yourself — dispatch all work. Exception: trivial ~5-line hotfixes
(typos, config tweaks, minor glue) where spawning a worker causes more friction
than editing directly; no run, brief, or extra approval cycle needed for those.
Do not edit files a running worker is changing.

When delegating, default to `worker`: supply the procedure, inputs, and outputs. It executes
and reports blockers instead of investigating. Select the existing `builder`
only for user-authorized investigation or implementation needing independent
choices. A delegated code edit with a known procedure still belongs to `worker`.

Neither O nor either agent tests, compares, or validates artifacts unless the
user explicitly requests it. Do not invent checks in the plan or brief. Normal
execution errors must be reported; `done` means execution completed, not verified.

State lives in the project, not in your context:

```
.ocq/runs/<run>/
  brief.md       goal, conventions, done criteria - every worker reads it
  run.json       agent, model, variant, concurrency, max_attempts, permission
  ledger.jsonl   append-only task state (only ocq writes it; never edit by hand)
  results/<id>.json   worker report: {"status", "artifact", "note"}
  results/<id>.ping   one-line ping on request; wait-any consumes it
```

## Commands

```bash
gski ocq init RUN [--agent worker|builder] [--model provider/model] [--variant V] [--concurrency N]
gski ocq add RUN "task text" ["task text"]... [--deps 0001,0002]
gski ocq add RUN --file tasks.jsonl        # {"task": "...", "id"?: "...", "deps"?: [...]} or plain lines
gski ocq ls                                # runs in this project
gski ocq ledger RUN [--status S...] [--all]  # counts + actionable rows
gski ocq spawn RUN                         # fill free slots with ready pending tasks
gski ocq spawn RUN ID... [--agent worker|builder] [--allow 'shell:ssh host *']... [--model M]
gski ocq wait-any RUN [--timeout 600]      # block until workers finish or ping
gski ocq result RUN ID                     # details + worker's last reply
gski ocq done RUN ID... [--note]
gski ocq retry RUN ID... [--feedback "what to fix"]
gski ocq fail RUN ID... [--note]
gski ocq abort RUN [ID...]                 # running -> pending, kills its background jobs
gski ocq send RUN ID "text" [--queue]      # message a running/reported worker; reported -> running
```

Task ids are zero-padded (`0001`); `1` also works.
Statuses: `pending` -> `running` -> `reported` -> `done` | `failed`, or back to
`pending` by `retry`/`abort`, or `reported` -> `running` by `send`.
`init --agent` sets the run default; `spawn --agent` overrides that dispatch only.
Repeat the override on retries. ocq sessions cannot delegate to subagents.

## Phase 1: understand, propose, wait

Before starting a worker run:

1. Read the supplied docs and inputs. Use the known procedure; do not rediscover it.
2. Send a plan to the user:
   - your understanding of the goal, in a few lines
   - how the work splits into tasks: count, and 2-3 concrete examples
   - the brief you will give workers (summary)
   - what execution must complete to count as "done"
   - concurrency, agent, model, extra permissions if any
3. Stop and wait for approval. Nothing is spawned before the user says go.

If the user wants a trial, run 1-3 tasks first and show results before the rest.

## Phase 2: set up

1. `gski ocq init RUN ...`
2. Write `brief.md`: goal, inputs, outputs, conventions, and completion criteria.
   For `worker`, give the procedure; for `builder`, give scope and constraints.
   Include checks only if the user requested them. Blockers go back to O with
   the reason and any partial work. Workers have no orchestrator conversation context.
3. Set extra permissions in `run.json` `permission`, same shape as opencode
   config: `{"shell": {"ssh myhost *": "allow"}, "webfetch": "deny"}`.
   Only what the user approved. Standing approval: always add
   `"external_directory": {"/tmp/opencode/**": "allow"}` (workers read scratch
   images there; without it Read is auto-denied).
4. Add tasks. Each task text is self-contained: what to do, which input, where
   the output goes. For many tasks write a jsonl file and `add --file`.
   Stack back-to-back steps into one task to save worker startup overhead.

## Phase 3: control loop

```
spawn RUN            -> fills slots up to concurrency
wait-any RUN         -> reports finished workers
read each report     -> done / retry --feedback / fail
repeat
```

Waiting:
- Run `wait-any` as a background shell command (`background: true`) with a
  long `--timeout`, e.g. `--timeout 3600`. You are notified when it returns;
  do not poll its output or check status in between.
- Always close a turn that starts background `wait-any` with a short one-liner
  (e.g. `waiting` or `0004 done, waiting`) — never an empty response.
- While it runs, the session stays free for the user. If they ask for status,
  `ledger RUN` is enough; the background wait keeps going.
- On `timeout: N running`, start it again in the background and reply `waiting`.

Reports:
- Accept successful execution reports. No artifact inspection, sampling, or
  verification loops unless the user requested them; stay within that request.
- Workers may note concrete instruction problems encountered during execution.
  Do not assign a separate instruction review or automatically rerun completed work.
- Mark several at once: `gski ocq done RUN 0004 0005 0006`.

Deciding:
- Bad result, fixable: `retry --feedback` with a concrete correction. The
  next attempt sees it.
- Worker `failed` with a real reason, or max attempts reached: `fail --note`.
- A procedure needs investigation: clarify it or use `builder` only within the
  approved scope. A worker never promotes itself to builder.
- The same failure pattern across tasks: stop spawning, fix the brief or
  task texts, tell the user if it changes the plan.
- `NNNN denied <tool>: <what>` lines: ocq auto-rejected a permission ask. If
  the task truly needs it, ask the user before allowing it (`spawn --allow`
  or `run.json`). Never grant permissions on your own.
- A worker running far longer than its peers: `result` to look, then
  `abort` + retry, or leave it.
- Workers may run background shell jobs; a worker idle while its job runs is
  still `running`, not finished. `wait-any` reports it only after the job ends
  and the worker's last turn is done.
- Small correction that needs the worker's context: `send RUN ID "..."`.
  It steers a running worker (`--queue`: after its current turn) or resumes a
  reported one in the same session. Use `retry --feedback` for a fresh attempt.

Pings (reactive only):
- A worker pings only when you ask: in the brief, the task text, or a `send`.
  It never pings on its own. Ask for a status now, or set a condition:
  `send RUN 0003 "ping when the migration step passes, then continue"`.
- The worker writes one line to `results/<id>.ping` and keeps working.
  `wait-any` returns with `NNNN ping | <text>`; the task stays `running`.
  React if needed, then restart `wait-any` in the background.

Context hygiene:
- Keep turns short. Don't restate the ledger; `ledger RUN` shows it.
- Use `result RUN ID` only when a report line is not enough.
- Never read worker transcripts in full.

## Phase 4: finish

When `ledger` shows nothing pending or running: a short summary for the
user - counts, failures grouped by reason, where the artifacts are, cost.
Include useful instruction feedback and an obvious correction for next time,
if any. Do not launch an investigation or repair project from that feedback.

## Resume

A new orchestrator session continues a run from files alone:
`gski ocq ls`, then `gski ocq ledger RUN`, then read `brief.md`. Running
workers keep going while no orchestrator is attached; `wait-any` picks them up.

## Errors

- `server not reachable`: ask the user to run `opencode service start`. Do not start it yourself.
- `brief missing`: write `brief.md` first.
- `max attempts reached`: use `fail`, or ask the user.
