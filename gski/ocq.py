import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

from gski.ocq_lib.api import (
    BASE_RULES,
    DEFAULT_PORT,
    EVENT_TYPES,
    active,
    api,
    assistants,
    create_session,
    die,
    err_text,
    interrupt,
    kill_shell,
    messages,
    open_events,
    pending_input,
    send_prompt,
    send_synthetic,
    session_info,
    shells,
    sweep,
    turn_text,
)
from gski.ocq_lib.ledger import (
    PARENT_TARGETS,
    append,
    build_prompt,
    cut,
    ensure_run,
    fold,
    known_projects,
    load_cfg,
    parse_allow,
    project_root,
    resolve,
    row,
    rules_from,
    run_dir,
    short_model,
    sum_tokens,
    summary,
)


def rules_for(cfg, allow=None):
    merged = list(dict.fromkeys((cfg.get("allow") or []) + list(allow or [])))
    return BASE_RULES + rules_from(cfg.get("permission")) + [parse_allow(a) for a in merged], merged


def settle_task(rd, cfg, t):
    msgs = messages(t["session"])
    asst = assistants(msgs)
    last = asst[0] if asst else None
    sent = t.get("sent") or t.get("started") or 0
    if sent and time.time() - sent < 120 and not (last and (last.get("time") or {}).get("created", 0) / 1000 >= sent):
        return None
    if last and pending_input(msgs):
        return None
    result = rd / "results" / f"{t['id']}.json"
    fresh = result.exists() and result.stat().st_mtime >= (sent - 1 if sent else 0)
    if not fresh and shells(t["session"], cfg["dir"]) != []:
        return None
    info = session_info(t["session"])
    if not last:
        if time.time() - (t.get("started") or 0) < 120:
            return None
        err = "no response from agent"
    elif last.get("error"):
        err = err_text(last["error"])
    elif not (last.get("time") or {}).get("completed"):
        return None
    elif info.get("outcome") in ("failed", "interrupted"):
        err = f"session {info['outcome']}"
    else:
        err = None

    reply = cut(turn_text(msgs), 200)
    art = t.get("artifact")
    if fresh:
        try:
            r = json.loads(result.read_text())
            status = "done" if r.get("status") == "done" and not err else "failed"
            art = r.get("artifact")
            note = r.get("note") or err or reply
        except (OSError, json.JSONDecodeError, AttributeError):
            status, note = "failed", err or f"invalid results/{t['id']}.json | {reply}"
    elif err:
        status, note = "failed", err
    elif t.get("prev_status") == "done":
        status, note = "done", reply or t.get("note")
    else:
        status, note = "failed", f"missing results/{t['id']}.json | {reply}"

    cost = round(info.get("cost") or sum(m.get("cost") or 0 for m in asst), 4)
    tokens = sum_tokens([info.get("tokens")] if info.get("tokens") else (m.get("tokens") for m in asst))
    append(
        rd,
        id=t["id"],
        status=status,
        worker=status,
        artifact=art,
        note=note,
        cost=cost,
        tokens=tokens,
        billed={"cost": cost, "tokens": tokens},
        finished=int(time.time()),
    )
    return f"{t['id']} {status}{short_model(t)} {art or '-'} | {cut(note, 120)}"


def check_run(rd, cfg):
    tasks = fold(rd)
    running = {t["session"]: t for t in tasks.values() if t["status"] == "running" and t.get("session")}
    if not running:
        return "empty", []
    sweep(rd, cfg, {sid: t["id"] for sid, t in running.items()}, append)
    live = active()
    if live is None:
        return "wait", []
    candidates = [t for sid, t in running.items() if sid not in live]
    if not candidates:
        return "wait", []
    need_pause = any(
        not (
            (rd / "results" / f"{t['id']}.json").exists()
            and (rd / "results" / f"{t['id']}.json").stat().st_mtime >= (t.get("sent") or t.get("started") or 0) - 1
        )
        for t in candidates
    )
    if need_pause:
        time.sleep(1.5)
        tasks = fold(rd)
        running = {t["session"]: t for t in tasks.values() if t["status"] == "running" and t.get("session")}
        sweep(rd, cfg, {sid: t["id"] for sid, t in running.items()}, append)
        live = active()
        if live is None:
            return "wait", []
    lines = []
    for c in candidates:
        t = running.get(c["session"])
        if t and c["session"] not in live:
            line = settle_task(rd, cfg, t)
            if line:
                lines.append(line)
    still = sum(1 for t in fold(rd).values() if t["status"] == "running")
    return ("empty" if still == 0 else "partial"), lines


def fmt_dur(s):
    h, rem = divmod(max(int(s), 0), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def notify(text, color):
    if not (shutil.which("hyprctl") and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")):
        return
    try:
        subprocess.Popen(
            ["hyprctl", "notify", "-1", "6000", color, f"fontsize:20 {text}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def next_id(tasks):
    nums = [int(k) for k in tasks if k.isdigit()]
    return f"{(max(nums) if nums else len(tasks)) + 1:04d}"


def cmd_spawn(args):
    items = [{"task": t} for t in args.text]
    if args.file:
        with (sys.stdin if args.file == "-" else open(args.file)) as src:
            for line in src:
                line = line.strip()
                if line:
                    items.append(json.loads(line) if line.startswith("{") else {"task": line})
    if not items:
        die("no tasks given (pass task strings or --file)")
    rd, cfg = ensure_run(args.run, args.allow)
    tasks = fold(rd)
    for it in items:
        if not it.get("task"):
            die(f"item without task: {it}")
        tid = str(it.get("id") or next_id(tasks))
        if tid in tasks:
            die(f"duplicate id: {tid}")
        agent = it.get("agent") or args.agent or cfg.get("agent") or "worker"
        model = it.get("model") or args.model or cfg.get("model")
        rules, item_allow = rules_for(cfg, list(args.allow or []) + list(it.get("allow") or []))
        (rd / "results" / f"{tid}.json").unlink(missing_ok=True)
        meta = {"ocq_root": str(cfg["dir"]), "run": args.run, "task": tid}
        s, used = create_session(f"ocq/{args.run}/{tid}", agent, model, rules, cfg["dir"], meta)
        now = time.time()
        t = {"id": tid, "task": it["task"]}
        send_prompt(s["id"], build_prompt(rd, args.run, t))
        model_id = used.split(" ")[0]
        tasks[tid] = t
        append(
            rd,
            id=tid,
            task=it["task"],
            agent=agent,
            model=model_id,
            status="running",
            session=s["id"],
            attempts=1,
            started=int(now),
            sent=round(now - 0.5, 3),
            allow=item_allow or None,
            msg=None,
        )
        print(f"{tid} running {s['id']} [{agent} · {used}]")


def cmd_wait(args):
    rd = run_dir(args.run)
    cfg = load_cfg(rd)
    deadline = time.time() + args.timeout
    collected = []

    def finish():
        tasks = fold(rd)
        print(summary(tasks))
        if collected and not any(t["status"] == "running" for t in tasks.values()):
            orch_sid = cfg.get("orchestrator")
            in_ocm = bool(orch_sid and str(session_info(orch_sid).get("title") or "").startswith("ocm/"))
            if not in_ocm:
                bad = any(t["status"] == "failed" for t in tasks.values())
                starts = [t["started"] for t in tasks.values() if t.get("started")]
                ends = [t["finished"] for t in tasks.values() if t.get("finished")]
                took = f" | {fmt_dur(max(ends) - min(starts))}" if starts and ends else ""
                notify(f"{args.run}: {summary(tasks).split(' | ')[0]}{took}", "rgb(fb4934)" if bad else "rgb(d79921)")

    def emit(lines):
        for line in lines:
            print(line, flush=True)
            collected.append(line)

    while True:
        rem = deadline - time.time()
        if rem <= 0:
            state, lines = check_run(rd, cfg)
            emit(lines)
            if state == "empty":
                if not collected:
                    print("nothing running")
                finish()
                return
            running = [t for t in fold(rd).values() if t["status"] == "running"]
            print(f"timeout: {len(running)} running")
            return
        try:
            with open_events(min(60.0, max(1.0, rem))) as resp:
                state, lines = check_run(rd, cfg)
                emit(lines)
                if state == "empty":
                    if not collected:
                        print("nothing running")
                    finish()
                    return
                if args.any and lines:
                    finish()
                    return
                last_check = time.time()
                while time.time() < deadline:
                    raw = resp.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        if time.time() - last_check >= 30:
                            last_check = time.time()
                            state, lines = check_run(rd, cfg)
                            emit(lines)
                            if state == "empty" or (args.any and lines):
                                finish()
                                return
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    etype = ev.get("type")
                    sid = (ev.get("data") or {}).get("sessionID")
                    running = {t["session"]: t for t in fold(rd).values() if t["status"] == "running" and t.get("session")}
                    if not running:
                        finish()
                        return
                    if etype == "permission.asked" and sid in running:
                        sweep(rd, cfg, {sid: running[sid]["id"]}, append)
                    elif etype == "shell.exited" or (sid in running and etype in EVENT_TYPES):
                        last_check = time.time()
                        state, lines = check_run(rd, cfg)
                        emit(lines)
                        if state == "empty" or (args.any and lines):
                            finish()
                            return
        except TimeoutError:
            state, lines = check_run(rd, cfg)
            emit(lines)
            if state == "empty" or (args.any and lines):
                finish()
                return
        except (urllib.error.URLError, OSError):
            if time.time() >= deadline:
                continue
            time.sleep(2)


def cmd_ls(args):
    if not args.run:
        runs = project_root() / ".ocq" / "runs"
        found = sorted(p for p in runs.glob("*") if (p / "run.json").exists()) if runs.exists() else []
        if not found:
            print("no runs")
        for rd in found:
            print(f"{rd.name}: {summary(fold(rd))}")
        return
    rd = run_dir(args.run)
    tasks = fold(rd)
    print(summary(tasks))
    for t in tasks.values():
        if not args.status or t["status"] in args.status:
            print(row(t))


def cmd_show(args):
    rd = run_dir(args.run)
    tasks = fold(rd)
    t = tasks[resolve(tasks, [args.id])[0]]
    cost = f"  cost: ${t['cost']:.4f}" if t.get("cost") else ""
    print(f"id: {t['id']}  status: {t['status']}  attempts: {t.get('attempts', 0)}  session: {t.get('session', '-')}{cost}")
    if t.get("agent") or t.get("model"):
        print(f"agent: {t.get('agent', 'worker')}  model: {t.get('model', '-')}")
    print(f"task: {t.get('task')}")
    for k in ("artifact", "note", "msg", "tokens"):
        if t.get(k) not in (None, ""):
            print(f"{k}: {t[k]}")
    for d in t.get("denied") or []:
        print(f"denied: {d}")
    if t.get("session"):
        txt = turn_text(messages(t["session"], limit=30))
        if txt:
            print("--- last reply ---")
            print(txt[: args.chars])


def caller_task(sid):
    if not sid:
        return None
    meta = session_info(sid).get("metadata") or {}
    if meta.get("ocq_root") and meta.get("run"):
        rd = Path(meta["ocq_root"]) / ".ocq" / "runs" / meta["run"]
        if (rd / "run.json").exists():
            for t in fold(rd).values():
                if t.get("session") == sid:
                    return rd, meta["run"], t
    roots = [project_root(), *(Path(p) for p in known_projects())]
    seen = set()
    for r in roots:
        try:
            r = r.resolve()
        except OSError:
            continue
        if r in seen:
            continue
        seen.add(r)
        runs = r / ".ocq" / "runs"
        if not runs.is_dir():
            continue
        for rd in runs.iterdir():
            if not (rd / "run.json").exists():
                continue
            for t in fold(rd).values():
                if t.get("session") == sid:
                    return rd, rd.name, t
    return None


def cmd_send(args):
    pos = args.target
    caller = os.environ.get("OPENCODE_SESSION_ID")
    mine = caller_task(caller) if caller else None
    if mine:
        rd, run_name, t = mine
        if args.allow:
            die("--allow is only for orchestrator -> worker")
        if len(pos) == 2:
            dst, text = pos
        elif len(pos) == 3 and pos[0] == run_name:
            _, dst, text = pos
        else:
            die("usage from worker: gski ocq send .. <text>")
        if dst not in PARENT_TARGETS:
            die("worker can only send to ..")
        orch = load_cfg(rd).get("orchestrator")
        if not orch:
            die("no orchestrator session recorded in run.json")
        send_synthetic(orch, f"[ocq/{run_name}/{t['id']}]\n{text}", f"ocq/{run_name}/{t['id']}")
        append(rd, id=t["id"], msg=cut(text, 300))
        print(f"{t['id']} -> .. sent")
        return
    if len(pos) == 2 and pos[0] in PARENT_TARGETS:
        die("not in a worker session")
    if len(pos) != 3 or pos[1] in PARENT_TARGETS:
        die("usage: gski ocq send <run> <id> <text>")
    run_name, tid_arg, text = pos
    rd = run_dir(run_name)
    cfg = load_cfg(rd)
    tasks = fold(rd)
    t = tasks[resolve(tasks, [tid_arg])[0]]
    if not t.get("session"):
        die(f"{t['id']} has no session")
    extra = list(dict.fromkeys((t.get("allow") or []) + list(args.allow or [])))
    rules, merged_allow = rules_for(cfg, extra)
    api("PATCH", f"/api/session/{t['session']}", {"permissions": rules})
    rel = f".ocq/runs/{run_name}/results/{t['id']}.json"
    prompt = (
        f'[ocq orchestrator — reply mid-run via `gski ocq send .. "..."` while keeping work/bg jobs running; '
        f'when finished, write {rel}: {{"status": "done" | "failed", "artifact": "<path or short value>", "note": "<one line>"}}]\n{text}'
    )
    delivery = "queue" if args.queue else "steer"
    now = time.time()
    send_prompt(t["session"], prompt, delivery)
    reopen = t["status"] != "running"
    ev = {
        "id": t["id"],
        "sent": round(now - 0.5, 3),
        "message": cut(text, 300),
        "allow": merged_allow or None,
    }
    if reopen:
        b = t.get("billed") or {}
        neg = {k: -v for k, v in (b.get("tokens") or {}).items()}
        ev.update(
            status="running",
            prev_status=t["status"],
            attempts=(t.get("attempts") or 1) + 1,
            cost=-(b.get("cost") or 0),
            tokens=neg or None,
            billed=None,
        )
    append(rd, **ev)
    print(f"{t['id']} sent ({delivery}){' -> running' if reopen else ''}")


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
        bg = shells(t["session"], cfg["dir"]) or []
        for s in bg:
            kill_shell(s["id"], cfg["dir"])
        interrupt(t["session"])
        for _ in range(10 if bg else 0):
            time.sleep(0.5)
            if t["session"] in (active() or {}):
                interrupt(t["session"])
        append(rd, id=tid, status="failed", worker="failed", note="aborted", finished=int(time.time()))
        print(f"{tid} aborted -> failed")


def cmd_serve(args):
    print(f"run workers against it with: OCQ_URL=http://127.0.0.1:{args.port} (set OCQ_PASSWORD if the server needs one)", file=sys.stderr)
    os.execvp("opencode", ["opencode", "serve", "--port", str(args.port), "--hostname", "127.0.0.1"])


def register(subparsers):
    p = subparsers.add_parser("ocq", help="orchestrate opencode worker sessions")
    sub = p.add_subparsers(dest="ocq_cmd", required=True)

    s = sub.add_parser("spawn", help="start worker task(s) immediately in parallel")
    s.add_argument("run")
    s.add_argument("text", nargs="*", help="task text, one worker per argument")
    s.add_argument("--file", help="jsonl ({task, id?, agent?, model?, allow?}) or plain lines; - for stdin")
    s.add_argument("--agent", help="worker (default) or builder")
    s.add_argument("--model", help="provider/model")
    s.add_argument("--allow", action="append", help="extra allow rule, e.g. 'shell:ssh host *'")
    s.set_defaults(func=cmd_spawn)

    s = sub.add_parser("wait", aliases=["wait-any"], help="sleep on SSE until running workers finish; auto-rejects permission asks")
    s.add_argument("run")
    s.add_argument("--any", action="store_true", help="return on first finished worker instead of waiting for all")
    s.add_argument("--timeout", type=int, default=3600)
    s.set_defaults(func=cmd_wait)

    s = sub.add_parser("ls", help="list runs, or tasks and results in <run>")
    s.add_argument("run", nargs="?")
    s.add_argument("--status", nargs="+")
    s.set_defaults(func=cmd_ls)

    s = sub.add_parser("show", help="show task details, result, and worker's last reply")
    s.add_argument("run")
    s.add_argument("id")
    s.add_argument("--chars", type=int, default=4000)
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("send", help="message/reopen a worker (<run> <id> <text>) or parent orchestrator (.. <text>)")
    s.add_argument("target", nargs="+", metavar="ARG", help="<run> <id> <text>, or .. <text> from a worker")
    s.add_argument("--queue", action="store_true", help="deliver after current turn instead of steering")
    s.add_argument("--allow", action="append", help="grant additional allow rule to the worker session")
    s.set_defaults(func=cmd_send)

    s = sub.add_parser("abort", help="abort running worker(s) (all if no ids) -> failed")
    s.add_argument("run")
    s.add_argument("ids", nargs="*")
    s.set_defaults(func=cmd_abort)

    s = sub.add_parser("serve", help="optional: run a standalone opencode server")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.set_defaults(func=cmd_serve)
