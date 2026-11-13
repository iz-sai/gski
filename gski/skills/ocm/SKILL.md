---
name: gski ocm
description: Manage opencode orchestrator sessions - align with the user on high-level goals, then autonomously run multi-stage work across orchestrators
---

# ocm

`gski ocm` drives `orchestrator` (`O`) sessions on the shared opencode background
service.

Why this layer exists:
- `O` is a team-lead for one bounded job: it inspects the codebase and inputs,
  designs a procedure, runs workers via `gski ocq`, reviews, and iterates.
- You (`M`) sit in the user's chair above `O` for larger, long-running (e.g.
  overnight), multi-part goals that do not fit into a single `O` session. You
  break a high-level goal into `O`-sized tasks, run multiple `O` sessions over
  time (sequentially by default; parallel only across separate directories),
  review their plans and outcomes, send mid-course or post-run corrections, and
  adapt the next task based on what actually happened.

Do not write or edit code, and do not read source code to design procedures for
`O`. Reading top-level docs (`AGENTS.md`, `README.md`, specs) to orient yourself
is fine; codebase investigation and worker breakdown belong to `O`.

State lives in `.ocm/ledger.jsonl` (append-only; only `ocm` writes it).

## Commands

```bash
gski ocm start <name> "task..." [--dir DIR] [--allow 'shell:git *']...
gski ocm ls                              # streams, status, costs, child ocq runs
gski ocm show <name> [--chars 4000]      # stream details + O's last turn reply
gski ocm wait [--timeout 3600]           # SSE sleep (zero CPU) until an O stops
gski ocm send <name> "text" [--queue] [--allow RULE]...
gski ocm done <name> [--note "..."]
gski ocm fail <name> [--note "..."]
gski ocm abort [<name>]                  # kills O's bg shells + interrupts -> reported
```

Statuses: `running` -> `reported` -> `done` | `failed`, or back to `running` via `send`.
`O` defaults to `google/gemini-4-carbon#medium`; do not pass `--model` unless the
user explicitly asks for a different model.
Never run two `O` streams concurrently in the same directory.

## Phase 1: align with the user

Before starting any `O` session:

1. Talk with the user until you clearly understand what they want built or done,
   what matters to them, constraints, and what counts as finished. Ask sharp,
   focused questions when something important is ambiguous; do not interrogate
   with boilerplate forms.
2. Outline the high-level plan: how you will stage the `O` tasks, plus any extra
   permissions needed (`ssh`, `git` writes, external directories).
3. Wait for explicit go-ahead before running `ocm start`.

## Phase 2: autonomous loop (default: handle it yourself)

Once the user says go, drive the campaign to completion on your own:

```
start <name> "..."   -> launches O on one bounded high-level task
wait                 -> sleeps on server events until O stops for input/completion
show <name>          -> read O's plan, question, or final report
decide               -> send (approve/steer/correct) | done -> start next O | fail
```

Briefing `O`:
- Give `O` a clear team-lead brief: what outcome is needed, why, relevant context
  from earlier stages, scope boundaries, and approved permissions.
- State goals and constraints, not code-level step-by-step instructions.

Waiting:
- Run `gski ocm wait --timeout 3600` as a background shell command
  (`background: true`). It subscribes to SSE events and uses zero CPU while `O`
  and its `ocq` workers run. Do not poll between notifications.
- Close any turn that starts background `wait` with a short one-liner
  (e.g. `01-core started, waiting` or `01-core plan approved, waiting`) — never
  an empty response.
- On `timeout: N running`, restart background `wait` and reply `waiting`.

Handling `O` reports (`reported`):
- **Phase 1 plan from `O`**: check via `show <name>` that the plan matches the
  stage goal and stays within agreed scope and permissions. Approve it yourself
  (`gski ocm send <name> "go"`) or send adjustments. Do not bounce routine `O`
  plans back to the user.
- **Mid-run question or systematic failure from `O`**: resolve it yourself when
  the answer follows from what you agreed with the user; steer with `ocm send`.
- **Completion report from `O`**: read `show <name>` critically. If something was
  missed, half-done, or drifted from intent, send concrete high-level corrections
  (`ocm send <name> "..."`) for another iteration in the same `O` session. When
  the stage is genuinely complete, mark `gski ocm done <name>` and start the next
  `O` session with a fresh context, carrying forward what the next stage needs
  to know.
- **`denied <action>: <resource>`**: `ocm` auto-rejected an unapproved permission
  ask. If the work truly requires it and the user did not pre-approve it, ask
  the user; once approved, grant it with `ocm send <name> "go" --allow '...'`.

When to come back to the user mid-run:
- Only when an unapproved permission is needed, or reality contradicts a core
  assumption so that guessing would violate what you agreed on. Otherwise keep
  going.

Context hygiene:
- Keep turns short. `.ocm/ledger.jsonl` (`ocm ls`) is the state of record.
- Do not read source code or worker transcripts.

## Phase 3: finish

When all stages are `done`: give a concise summary of what was accomplished
across stages, key outcomes/paths, any caveats, and total cost (`O` + `ocq`).

## Resume

A new Manager session resumes from files alone: `gski ocm ls`, then
`gski ocm show <name>` on active or reported streams. Running `O` sessions keep
working while detached; `gski ocm wait` reconnects to them.
