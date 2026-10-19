import json
import os
import sys
import time
from pathlib import Path

from gski.ocq_lib.api import (
    BASE_RULES,
    DEFAULT_CFG,
    DEFAULT_PORT,
    active,
    assistants,
    create_session,
    err_text,
    interrupt,
    last_text,
    messages,
    send_prompt,
    session_info,
    sweep,
)
from gski.ocq_lib.ledger import (
    SHOW,
    append,
    build_prompt,
    cut,
    fold,
    load_cfg,
    parse_allow,
    project_root,
    remember,
    resolve,
    row,
    rules_from,
    run_dir,
    sum_tokens,
    summary,
)


def report(rd, cfg, t):
    msgs = messages(t["session"])
    asst = assistants(msgs)
    last = asst[0] if asst else None
    info = session_info(t["session"])
    if not last:
        if time.time() - t.get("started", 0) < 120:
            return None
        err = "no response from agent"
    elif last.get("error"):
        err = err_text(last["error"])
    elif not last.get("time", {}).get("completed"):
        return None
    elif info.get("outcome") in ("failed", "interrupted"):
        err = f"session {info['outcome']}"
    else:
        err = None

    ws, art, note = "missing", None, cut(last_text(msgs), 200)
    try:
        r = json.loads((rd / "results" / f"{t['id']}.json").read_text())
        ws, art, note = r.get("status", "?"), r.get("artifact"), r.get("note") or note
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, AttributeError):
        ws = "invalid"

    if err and ws in ("missing", "invalid"):
        ws, note = "error", err

    cost = round(info.get("cost") or sum(m.get("cost") or 0 for m in asst), 4)
    tokens = sum_tokens([info.get("tokens")] if info.get("tokens") else (m.get("tokens") for m in asst))
    append(rd, id=t["id"], status="reported", worker=ws, artifact=art, note=note, cost=cost, tokens=tokens, finished=int(time.time()))
    return f"{t['id']} {ws} {art or '-'} | {cut(note, 120)}"


def cmd_serve(args):
    print(f"run workers against it with: OCQ_URL=http://127.0.0.1:{args.port} (set OCQ_PASSWORD if the server needs one)", file=sys.stderr)
    os.execvp("opencode", ["opencode", "serve", "--port", str(args.port), "--hostname", "127.0.0.1"])


def cmd_init(args):
    root = project_root()
    base = root / ".ocq"
    base.mkdir(exist_ok=True)
    gi = base / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n")
    rd = base / "runs" / args.run
    (rd / "results").mkdir(parents=True, exist_ok=True)
    cfg_path = rd / "run.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {**DEFAULT_CFG}
    for k in ("agent", "model", "variant", "concurrency"):
        v = getattr(args, k)
        if v is not None:
            cfg[k] = v
    cfg["dir"] = str(root)
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    remember(root)
    brief = rd / "brief.md"
    print(f"run:    {args.run}")
    print(f"config: {cfg_path}")
    print(f"brief:  {brief}" + ("" if brief.exists() else "  (missing: write it before spawn)"))


def cmd_add(args):
    rd = run_dir(args.run)
    tasks = fold(rd)
    items = [{"task": t} for t in args.text]
    if args.file:
        src = sys.stdin if args.file == "-" else open(args.file)
        for line in src:
            line = line.strip()
            if line:
                items.append(json.loads(line) if line.startswith("{") else {"task": line})
    deps = [d for d in (args.deps or "").split(",") if d]
    n = len(tasks)
    added = 0
    for it in items:
        if not it.get("task"):
            from gski.ocq_lib.api import die
            die(f"item without task: {it}")
        n += 1
        tid = str(it.get("id") or f"{n:04d}")
        if tid in tasks:
            from gski.ocq_lib.api import die
            die(f"duplicate id: {tid}")
        tasks[tid] = it
        append(rd, id=tid, task=it["task"], deps=it.get("deps") or deps, status="pending", attempts=0)
        added += 1
    print(f"added {added} (total {len(tasks)})")


def cmd_ls(args):
    runs = project_root() / ".ocq" / "runs"
    found = sorted(p for p in runs.glob("*") if (p / "run.json").exists()) if runs.exists() else []
    if not found:
        print("no runs")
    for rd in found:
        print(f"{rd.name}: {summary(fold(rd))}")


def cmd_ledger(args):
    tasks = fold(run_dir(args.run))
    print(summary(tasks))
    for t in tasks.values():
        if args.all or (t["status"] in args.status if args.status else t["status"] in SHOW):
            print(row(t))


def cmd_spawn(args):
    rd = run_dir(args.run)
    if not (rd / "brief.md").exists():
        from gski.ocq_lib.api import die
        die(f"brief missing: {rd / 'brief.md'}")
    cfg = load_cfg(rd)
    remember(cfg["dir"])
    tasks = fold(rd)
    running = [t for t in tasks.values() if t["status"] == "running"]
    if args.ids:
        targets = [tasks[i] for i in resolve(tasks, args.ids)]
        for t in targets:
            if t["status"] == "running":
                from gski.ocq_lib.api import die
                die(f"{t['id']} already running")
    else:
        free = int(cfg["concurrency"]) - len(running)
        pending = [t for t in tasks.values() if t["status"] == "pending"]
        ready = [t for t in pending if all(tasks.get(d, {}).get("status") == "done" for d in t.get("deps") or [])]
        if free <= 0:
            print(f"no free slots ({len(running)} running)")
            return
        if not ready:
            print(f"no ready tasks ({len(pending)} pending)" if pending else "no pending tasks")
            return
        targets = ready[:free]
    agent = args.agent or cfg["agent"]
    model = args.model or cfg.get("model")
    variant = args.variant or cfg.get("variant")
    rules = BASE_RULES + rules_from(cfg.get("permission")) + [parse_allow(a) for a in args.allow or []]
    for t in targets:
        t["attempts"] = t.get("attempts", 0) + 1
        (rd / "results" / f"{t['id']}.json").unlink(missing_ok=True)
        s, used = create_session(f"ocq/{args.run}/{t['id']}", agent, model, variant, rules, cfg["dir"])
        send_prompt(s["id"], build_prompt(args.run, t))
        append(rd, id=t["id"], status="running", session=s["id"], attempts=t["attempts"], started=int(time.time()), allow=args.allow or None)
        print(f"{t['id']} running {s['id']} [{used}]")


def cmd_wait(args):
    rd = run_dir(args.run)
    cfg = load_cfg(rd)
    deadline = time.time() + args.timeout
    while True:
        tasks = fold(rd)
        running = {t["session"]: t for t in tasks.values() if t["status"] == "running"}
        if not running:
            print("nothing running")
            return
        sweep(rd, cfg, {sid: t["id"] for sid, t in running.items()}, append)
        live = active() or {}
        lines = []
        for sid, t in running.items():
            if sid not in live:
                line = report(rd, cfg, t)
                if line:
                    lines.append(line)
        if lines:
            print("\n".join(lines))
            print(summary(fold(rd)))
            return
        if time.time() >= deadline:
            print(f"timeout: {len(running)} running")
            return
        time.sleep(args.interval)


def cmd_result(args):
    rd = run_dir(args.run)
    cfg = load_cfg(rd)
    tasks = fold(rd)
    t = tasks[resolve(tasks, [args.id])[0]]
    print(f"id: {t['id']}  status: {t['status']}  attempts: {t.get('attempts', 0)}  session: {t.get('session', '-')}")
    print(f"task: {t.get('task')}")
    for k in ("worker", "artifact", "note", "feedback", "cost", "tokens"):
        if t.get(k) not in (None, ""):
            print(f"{k}: {t[k]}")
    for d in t.get("denied") or []:
        print(f"denied: {d}")
    if t.get("session"):
        txt = last_text(messages(t["session"]))
        if txt:
            print("--- last reply ---")
            print(txt[: args.chars])


def mark(args, status):
    rd = run_dir(args.run)
    cfg = load_cfg(rd)
    tasks = fold(rd)
    for tid in resolve(tasks, args.ids):
        t = tasks[tid]
        if t["status"] == "running":
            print(f"{tid} running, abort first")
            continue
        if status == "pending":
            if t.get("attempts", 0) >= int(cfg["max_attempts"]):
                print(f"{tid} max attempts ({cfg['max_attempts']}) reached, use fail")
                continue
            append(rd, id=tid, status="pending", feedback=args.feedback)
        else:
            ev = {"id": tid, "status": status}
            if args.note:
                ev["note"] = args.note
            append(rd, **ev)
        print(f"{tid} {status}")


def cmd_abort(args):
    rd = run_dir(args.run)
    cfg = load_cfg(rd)
    tasks = fold(rd)
    ids = resolve(tasks, args.ids) if args.ids else [t["id"] for t in tasks.values() if t["status"] == "running"]
    for tid in ids:
        t = tasks[tid]
        if t["status"] != "running":
            print(f"{tid} not running")
            continue
        interrupt(t["session"])
        append(rd, id=tid, status="pending", note="aborted")
        print(f"{tid} aborted -> pending")


def register(subparsers):
    p = subparsers.add_parser("ocq", help="orchestrate opencode worker sessions")
    sub = p.add_subparsers(dest="ocq_cmd", required=True)

    s = sub.add_parser("serve", help="optional: run a separate opencode server for workers (default: shared background service)")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("init", help="create or update a run")
    s.add_argument("run")
    s.add_argument("--agent")
    s.add_argument("--model", help="provider/model")
    s.add_argument("--variant")
    s.add_argument("--concurrency", type=int)
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("add", help="add tasks")
    s.add_argument("run")
    s.add_argument("text", nargs="*", help="task text, one task per argument")
    s.add_argument("--file", help="jsonl ({task, id?, deps?}) or plain lines; - for stdin")
    s.add_argument("--deps", help="comma-separated ids for tasks given as text")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("ls", help="list runs")
    s.set_defaults(func=cmd_ls)

    s = sub.add_parser("ledger", help="show run state")
    s.add_argument("run")
    s.add_argument("--status", nargs="+")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_ledger)

    s = sub.add_parser("spawn", help="start workers: given ids, or fill free slots")
    s.add_argument("run")
    s.add_argument("ids", nargs="*")
    s.add_argument("--allow", action="append", help="extra allow rule, e.g. 'shell:ssh host *' or 'webfetch'")
    s.add_argument("--agent")
    s.add_argument("--model", help="provider/model")
    s.add_argument("--variant")
    s.set_defaults(func=cmd_spawn)

    s = sub.add_parser("wait-any", help="block until a worker finishes; auto-rejects permission asks")
    s.add_argument("run")
    s.add_argument("--timeout", type=int, default=600)
    s.add_argument("--interval", type=float, default=2)
    s.set_defaults(func=cmd_wait)

    s = sub.add_parser("result", help="show task details and last worker reply")
    s.add_argument("run")
    s.add_argument("id")
    s.add_argument("--chars", type=int, default=1500)
    s.set_defaults(func=cmd_result)

    for name, status in (("done", "done"), ("fail", "failed")):
        s = sub.add_parser(name, help=f"mark tasks {status}")
        s.add_argument("run")
        s.add_argument("ids", nargs="+")
        s.add_argument("--note")
        s.set_defaults(func=lambda a, st=status: mark(a, st))

    s = sub.add_parser("retry", help="send tasks back to pending")
    s.add_argument("run")
    s.add_argument("ids", nargs="+")
    s.add_argument("--feedback", help="shown to the next attempt")
    s.set_defaults(func=lambda a: mark(a, "pending"))

    s = sub.add_parser("abort", help="abort running workers (all if no ids) -> pending")
    s.add_argument("run")
    s.add_argument("ids", nargs="*")
    s.set_defaults(func=cmd_abort)

    s = sub.add_parser("dash", help="read-only web dashboard of all runs")
    s.add_argument("--port", type=int, default=4097)
    s.set_defaults(func=lambda a: __import__("gski.ocq_lib.dash", fromlist=["run"]).run(a))
