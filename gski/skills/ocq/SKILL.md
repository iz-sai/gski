---
name: gski ocq
description: Orchestrate opencode worker sessions - split repetitive work into tasks, run each in a fresh worker session, verify results, track state in a ledger
---

# ocq

`gski ocq` runs tasks in separate opencode worker sessions on the shared
opencode background service (auto-started; `OCQ_URL`/`OCQ_PASSWORD` target
another server, `gski ocq serve` runs a separate one). You are the orchestrator:
you plan, dispatch, verify, and decide. Workers do the tasks. You never do
tasks yourself.

State lives in the project, not in your context:

```
.ocq/runs/<run>/
  brief.md       goal, conventions, done criteria - every worker reads it
  run.json       agent, model, variant, concurrency, max_attempts, permission
  ledger.jsonl   append-only task state (only ocq writes it; never edit by hand)
  results/<id>.json   worker report: {"status", "artifact", "note"}
```

## Commands

```bash
gski ocq init RUN [--agent worker] [--model provider/model] [--variant V] [--concurrency N]
gski ocq add RUN "task text" ["task text"]... [--deps 0001,0002]
gski ocq add RUN --file tasks.jsonl        # {"task": "...", "id"?: "...", "deps"?: [...]} or plain lines
gski ocq ls                                # runs in this project
gski ocq ledger RUN [--status S...] [--all]  # counts + actionable rows
gski ocq spawn RUN                         # fill free slots with ready pending tasks
gski ocq spawn RUN ID... [--allow 'shell:ssh host *']... [--model M]
gski ocq wait-any RUN [--timeout 600]      # block until workers finish
gski ocq result RUN ID                     # details + worker's last reply
gski ocq done RUN ID... [--note]
gski ocq retry RUN ID... [--feedback "what to fix"]
gski ocq fail RUN ID... [--note]
gski ocq abort RUN [ID...]                 # running -> pending
```

Task ids are zero-padded (`0001`); `1` also works.
Statuses: `pending` -> `running` -> `reported` -> `done` | `failed`, or back to
`pending` by `retry`/`abort`.

## Phase 1: understand, propose, wait

Before anything runs:

1. Read the user's docs and inputs. Work out what one task is.
2. Send a plan to the user:
   - your understanding of the goal, in a few lines
   - how the work splits into tasks: count, and 2-3 concrete examples
   - the brief you will give workers (summary)
   - what "done" means and how you will verify it
   - concurrency, agent, model, extra permissions if any
3. Stop and wait for approval. Nothing is spawned before the user says go.

If the user wants a trial, run 1-3 tasks first and show results before the rest.

## Phase 2: set up

1. `gski ocq init RUN ...`
2. Write `brief.md`: goal, inputs and where they are, conventions, where
   artifacts go, exact done criteria, what to do when unsure (fail with a
   reason, never guess). Workers see only the brief and their task text.
3. Set extra permissions in `run.json` `permission`, same shape as opencode
   config: `{"shell": {"ssh myhost *": "allow"}, "webfetch": "deny"}`.
   Only what the user approved.
4. Add tasks. Each task text is self-contained: what to do, which input, where
   the output goes. For many tasks write a jsonl file and `add --file`.

## Phase 3: control loop

```
spawn RUN            -> fills slots up to concurrency
wait-any RUN         -> reports finished workers
verify each report   -> done / retry --feedback / fail
repeat
```

Waiting:
- Run `wait-any` as a background shell command (`background: true`) with a
  long `--timeout`, e.g. `--timeout 3600`. You are notified when it returns;
  do not poll its output or check status in between.
- While it runs, the session stays free for the user. If they ask for status,
  `ledger RUN` is enough; the background wait keeps going.
- On `timeout: N running`, start it again in the background. No commentary.

Verifying:
- The worker saying `done` is a claim, not a fact. Check the artifact against
  the done criteria with the cheapest real check: read the file, run the
  test, grep the output.
- For large uniform runs, check every report line, and open a sample of
  artifacts. Open more if anything looks off.
- Mark several at once: `gski ocq done RUN 0004 0005 0006`.

Deciding:
- Bad result, fixable: `retry --feedback` with a concrete correction. The
  next attempt sees it.
- Worker `failed` with a real reason, or max attempts reached: `fail --note`.
- The same failure pattern across tasks: stop spawning, fix the brief or
  task texts, tell the user if it changes the plan.
- `NNNN denied <tool>: <what>` lines: ocq auto-rejected a permission ask. If
  the task truly needs it, ask the user before allowing it (`spawn --allow`
  or `run.json`). Never grant permissions on your own.
- A worker running far longer than its peers: `result` to look, then
  `abort` + retry, or leave it.

Context hygiene:
- Keep turns short. Don't restate the ledger; `ledger RUN` shows it.
- Use `result RUN ID` only when a report line is not enough.
- Never read worker transcripts in full.

## Phase 4: finish

When `ledger` shows nothing pending or running: a short summary for the
user - counts, failures grouped by reason, where the artifacts are, cost.

## Resume

A new orchestrator session continues a run from files alone:
`gski ocq ls`, then `gski ocq ledger RUN`, then read `brief.md`. Running
workers keep going while no orchestrator is attached; `wait-any` picks them up.

## Errors

- `server not reachable`: ask the user to run `opencode service start`. Do not start it yourself.
- `brief missing`: write `brief.md` first.
- `max attempts reached`: use `fail`, or ask the user.
