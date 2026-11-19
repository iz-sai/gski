import json
import os
import re
import time
import urllib.error
from pathlib import Path

from gski.ocq_lib.api import (
    EVENT_TYPES,
    TMP_RULES,
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
from gski.ocq_lib.ledger import cut, fold as fold_ocq, known_projects, parse_allow, remember, sum_tokens, summary as ocq_summary

NAME_RE = re.compile(r"^[\w.-]+$")
PARENT_TARGETS = ("..", "manager", "parent")
OCM_RULES = [
    {"action": "question", "resource": "*", "effect": "deny"},
    {"action": "shell", "resource": "gski ocm*", "effect": "deny"},
    {"action": "shell", "resource": "gski ocm send *", "effect": "allow"},
    *TMP_RULES,
]


def ocm_root():
    cwd = Path.cwd()
    for d in [cwd, *cwd.parents]:
        if (d / ".ocm").is_dir():
            return d
    return cwd


def ensure_base():
    root = ocm_root()
    base = root / ".ocm"
    base.mkdir(exist_ok=True)
    gi = base / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n")
    remember(root)
    return base


def manager_sid(streams=None):
    sid = os.environ.get("OPENCODE_SESSION_ID")
    if not sid:
        return None
    if streams and any(s.get("session") == sid for s in streams.values()):
        return None
    return sid


def touch_manager(base, streams=None):
    remember(base.parent)
    sid = manager_sid(streams if streams is not None else fold(base))
    if not sid:
        return None
    p = base / "ocm.json"
    try:
        cfg = json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        cfg = {}
    if cfg.get("manager") != sid:
        cfg["manager"] = sid
        p.write_text(json.dumps(cfg, indent=2) + "\n")
    return sid


def read_manager(base, s):
    p = base / "ocm.json"
    try:
        mgr = json.loads(p.read_text()).get("manager") if p.exists() else None
    except (OSError, ValueError):
        mgr = None
    return mgr or s.get("manager")


def caller_stream(sid):
    if not sid:
        return None
    roots = []
    local = ocm_root()
    if (local / ".ocm" / "ledger.jsonl").exists():
        roots.append(local)
    meta = session_info(sid).get("metadata") or {}
    if meta.get("ocm_root"):
        roots.append(Path(meta["ocm_root"]))
    roots.extend(Path(p) for p in known_projects())
    seen = set()
    for r in roots:
        try:
            r = r.resolve()
        except OSError:
            continue
        if r in seen:
            continue
        seen.add(r)
        base = r / ".ocm"
        if not (base / "ledger.jsonl").exists():
            continue
        streams = fold(base)
        for s in streams.values():
            if s.get("session") == sid:
                return base, streams, s
    return None


def base_dir(must=True):
    base = ocm_root() / ".ocm"
    if must and not (base / "ledger.jsonl").exists():
        die("no ocm streams in this project")
    return base


def append(base, **ev):
    p = base / "ledger.jsonl"
    with open(p, "ab+") as f:
        f.seek(0, os.SEEK_END)
        if f.tell():
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write((json.dumps({"t": int(time.time()), **ev}, ensure_ascii=False) + "\n").encode())


def fold(base):
    streams = {}
    p = base / "ledger.jsonl"
    if not p.exists():
        return streams
    for line in p.read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        s = streams.setdefault(ev["id"], {"id": ev["id"], "cost": 0})
        s["updated"] = ev.pop("t", None)
        denied = ev.pop("denied", None)
        if denied:
            s.setdefault("denied", []).append(denied)
        s.update(ev)
    return streams


def get_stream(streams, name):
    if name not in streams:
        die(f"unknown stream: {name}")
    return streams[name]


def rules_for(allow):
    return OCM_RULES + [parse_allow(a) for a in allow or []]


def build_prompt(name, text):
    return (
        f"ocm stream: {name}\n"
        "Upstream is a Manager session. Execution is pre-approved within the goal, constraints, and permissions below: "
        "plan and run Round 1 directly without pausing for routine plan approval, then stop and report concrete results "
        "(stop early only on a genuine scope contradiction or missing permission).\n"
        "The question tool is disabled; upstream receives your output when you stop with no background jobs running, "
        'or mid-run via: gski ocm send .. "..."\n\n'
        f"Task:\n{text}"
    )


def ocq_runs(s):
    runs_dir = Path(s["dir"]) / ".ocq" / "runs"
    if not runs_dir.is_dir():
        return []
    out = []
    for rd in sorted(runs_dir.iterdir()):
        cfg_p = rd / "run.json"
        if not cfg_p.exists():
            continue
        try:
            cfg = json.loads(cfg_p.read_text())
        except (OSError, ValueError):
            continue
        if cfg.get("orchestrator") == s.get("session"):
            tasks = fold_ocq(rd)
            cost = sum(t.get("cost") or 0 for t in tasks.values())
            running = sum(1 for t in tasks.values() if t.get("status") == "running")
            out.append((rd.name, ocq_summary(tasks), cost, running))
    return out


def summary(streams):
    counts = {}
    o_cost = 0.0
    w_cost = 0.0
    for s in streams.values():
        counts[s["status"]] = counts.get(s["status"], 0) + 1
        c = s.get("cost") or 0
        if s["status"] == "running" and s.get("session"):
            c = max(c, session_info(s["session"]).get("cost") or 0)
        o_cost += c
        w_cost += sum(r[2] for r in ocq_runs(s))
    order = ["running", "reported", "done", "failed"]
    parts = [f"{k} {counts[k]}" for k in order if counts.get(k)]
    ocq_part = f" (+ ${w_cost:.2f} ocq)" if w_cost else ""
    return f"{len(streams)} streams: " + (", ".join(parts) or "empty") + f" | cost ${o_cost:.2f}{ocq_part}"


def settle_report(base, s):
    sid, d = s["session"], s["dir"]
    msgs = messages(sid, limit=20)
    asst = assistants(msgs)
    last = asst[0] if asst else None
    sent = s.get("sent") or 0
    if time.time() - sent < 120 and not (last and (last.get("time") or {}).get("created", 0) / 1000 >= sent):
        return None
    if last and pending_input(msgs):
        return None
    if shells(sid, d) != []:
        return None
    info = session_info(sid)
    if not last:
        err = "no response from orchestrator"
    elif last.get("error"):
        err = err_text(last["error"])
    elif not (last.get("time") or {}).get("completed"):
        return None
    elif info.get("outcome") in ("failed", "interrupted"):
        err = f"session {info['outcome']}"
    else:
        err = None
    reply = err or cut(turn_text(msgs), 240) or "(no text reply)"
    cost = round(info.get("cost") or 0, 4)
    tokens = sum_tokens([info.get("tokens")]) if info.get("tokens") else None
    append(base, id=s["id"], status="reported", note=reply, error=err, cost=cost, tokens=tokens, finished=int(time.time()))
    tag = "error" if err else "reported"
    return f"{s['id']} {tag} | {cut(reply, 120)}"


def check_all(base):
    streams = fold(base)
    running = {s["session"]: s for s in streams.values() if s["status"] == "running"}
    if not running:
        return "empty", []
    sweep(base, None, {sid: s["id"] for sid, s in running.items()}, append)
    live = active()
    if live is None:
        return "wait", []
    candidates = [s for sid, s in running.items() if sid not in live and shells(sid, s["dir"]) == []]
    if not candidates:
        return "wait", []
    time.sleep(2)
    streams = fold(base)
    running = {s["session"]: s for s in streams.values() if s["status"] == "running"}
    sweep(base, None, {sid: s["id"] for sid, s in running.items()}, append)
    live = active()
    if live is None:
        return "wait", []
    lines = []
    for c in candidates:
        s = running.get(c["session"])
        if s and c["session"] not in live:
            line = settle_report(base, s)
            if line:
                lines.append(line)
    return ("done", lines) if lines else ("wait", [])


def cmd_start(args):
    if args.name in PARENT_TARGETS or not NAME_RE.match(args.name):
        die(f"invalid stream name: {args.name}")
    base = ensure_base()
    streams = fold(base)
    if args.name in streams:
        die(f"stream already exists: {args.name} (use send to continue it, or pick a new name)")
    d = str(Path(args.dir).expanduser().resolve()) if args.dir else str(Path.cwd().resolve())
    if not Path(d).is_dir():
        die(f"directory not found: {d}")
    remember(d)
    mgr = touch_manager(base, streams)
    allow = list(args.allow or [])
    meta = {"ocm_root": str(base.parent), "stream": args.name}
    s, used = create_session(f"ocm/{args.name}", "orchestrator", args.model, rules_for(allow), d, meta)
    now = time.time()
    send_prompt(s["id"], build_prompt(args.name, args.text))
    append(
        base,
        id=args.name,
        status="running",
        session=s["id"],
        dir=d,
        model=used,
        task=args.text,
        allow=allow,
        started=int(now),
        sent=round(now - 0.5, 3),
        **({"manager": mgr} if mgr else {}),
    )
    print(f"{args.name} running {s['id']} [{used}] ({d})")


def cmd_ls(args):
    base = ocm_root() / ".ocm"
    streams = fold(base) if (base / "ledger.jsonl").exists() else {}
    if streams:
        touch_manager(base, streams)
    if not streams:
        print("no streams")
        return
    print(summary(streams))
    for s in streams.values():
        if args.status and s["status"] not in args.status:
            continue
        cost = s.get("cost") or 0
        if s["status"] == "running" and s.get("session"):
            cost = max(cost, session_info(s["session"]).get("cost") or 0)
        denied = f" [denied {len(s['denied'])}]" if s.get("denied") else ""
        if s["status"] in ("reported", "done", "failed") and s.get("note"):
            info = s["note"]
        elif s["status"] == "running" and s.get("msg"):
            info = f"msg: {s['msg']}"
        else:
            info = s.get("task", "")
        print(cut(f"{s['id']} {s['status']} ${cost:.2f}{denied} | {info}"))
        for rname, rsum, _, _ in ocq_runs(s):
            print(cut(f"  ocq/{rname}: {rsum}"))


def cmd_show(args):
    base = base_dir()
    streams = fold(base)
    touch_manager(base, streams)
    s = get_stream(streams, args.name)
    cost = s.get("cost") or 0
    if s["status"] == "running" and s.get("session"):
        cost = max(cost, session_info(s["session"]).get("cost") or 0)
    print(f"id: {s['id']}  status: {s['status']}  session: {s.get('session', '-')}  cost: ${cost:.4f}")
    print(f"dir: {s.get('dir')}  model: {s.get('model', '-')}")
    if s.get("allow"):
        print(f"allow: {', '.join(s['allow'])}")
    print(f"task: {s.get('task')}")
    if s.get("note"):
        print(f"note: {s['note']}")
    if s.get("msg"):
        print(f"msg: {s['msg']}")
    for d in s.get("denied") or []:
        print(f"denied: {d}")
    for rname, rsum, _, _ in ocq_runs(s):
        print(f"ocq/{rname}: {rsum}")
    if s.get("session"):
        txt = turn_text(messages(s["session"], limit=30))
        if txt:
            print("--- last reply ---")
            print(txt[: args.chars])


def finish_wait(base, lines):
    print("\n".join(lines))
    print(summary(fold(base)))


def cmd_wait(args):
    base = base_dir()
    touch_manager(base)
    deadline = time.time() + args.timeout
    while True:
        rem = deadline - time.time()
        if rem <= 0:
            running = [s for s in fold(base).values() if s["status"] == "running"]
            print(f"timeout: {len(running)} running")
            return
        try:
            with open_events(min(60.0, max(1.0, rem))) as resp:
                state, lines = check_all(base)
                if state == "empty":
                    print("nothing running")
                    return
                if state == "done":
                    finish_wait(base, lines)
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
                            state, lines = check_all(base)
                            if state == "empty":
                                print("nothing running")
                                return
                            if state == "done":
                                finish_wait(base, lines)
                                return
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    etype = ev.get("type")
                    sid = (ev.get("data") or {}).get("sessionID")
                    streams = fold(base)
                    running = {s["session"]: s for s in streams.values() if s["status"] == "running"}
                    if not running:
                        print("nothing running")
                        return
                    if etype == "permission.asked" and sid in running:
                        sweep(base, None, {sid: running[sid]["id"]}, append)
                    elif etype == "shell.exited" or (sid in running and etype in EVENT_TYPES):
                        last_check = time.time()
                        state, lines = check_all(base)
                        if state == "empty":
                            print("nothing running")
                            return
                        if state == "done":
                            finish_wait(base, lines)
                            return
        except TimeoutError:
            state, lines = check_all(base)
            if state == "empty":
                print("nothing running")
                return
            if state == "done":
                finish_wait(base, lines)
                return
        except (urllib.error.URLError, OSError):
            if time.time() >= deadline:
                continue
            time.sleep(2)


def cmd_send(args):
    caller = os.environ.get("OPENCODE_SESSION_ID")
    mine = caller_stream(caller) if caller else None
    if mine:
        base, _, s = mine
        if args.name not in PARENT_TARGETS:
            die("orchestrator can only send to ..")
        if args.allow:
            die("--allow is only for manager -> stream")
        mgr = read_manager(base, s)
        if not mgr:
            die("no manager session recorded in .ocm/ocm.json")
        send_synthetic(mgr, f"[ocm/{s['id']}]\n{args.text}", f"ocm/{s['id']}")
        append(base, id=s["id"], msg=cut(args.text, 300))
        print(f"{s['id']} -> .. sent")
        return
    if args.name in PARENT_TARGETS:
        die("not in an orchestrator session")
    base = base_dir()
    streams = fold(base)
    s = get_stream(streams, args.name)
    if s["status"] == "failed" or not s.get("session"):
        die(f"{s['id']} is {s['status']}: cannot send (start a new stream)")
    mgr = touch_manager(base, streams)
    allow = list(dict.fromkeys((s.get("allow") or []) + list(args.allow or [])))
    api("PATCH", f"/api/session/{s['session']}", {"permissions": rules_for(allow)})
    delivery = "queue" if args.queue else "steer"
    prompt = f'[ocm manager — reply via `gski ocm send .. "..."` while keeping bg jobs running]\n{args.text}'
    now = time.time()
    send_prompt(s["session"], prompt, delivery)
    was = s["status"]
    append(
        base,
        id=s["id"],
        status="running",
        sent=round(now - 0.5, 3),
        message=cut(args.text, 300),
        allow=allow,
        error=None,
        **({"manager": mgr} if mgr else {}),
    )
    arrow = " -> running" if was != "running" else ""
    print(f"{s['id']} sent ({delivery}){arrow}")


def cmd_mark(args, status):
    base = base_dir()
    streams = fold(base)
    s = get_stream(streams, args.name)
    if s["status"] == "running":
        die(f"{s['id']} is running, abort first")
    touch_manager(base, streams)
    ev = {"id": s["id"], "status": status}
    if args.note:
        ev["note"] = args.note
    append(base, **ev)
    print(f"{s['id']} {status}")


def cmd_abort(args):
    base = base_dir()
    streams = fold(base)
    touch_manager(base, streams)
    targets = [get_stream(streams, args.name)] if args.name else [s for s in streams.values() if s["status"] == "running"]
    for s in targets:
        if s["status"] != "running":
            print(f"{s['id']} not running")
            continue
        sid, d = s["session"], s["dir"]
        bg = shells(sid, d) or []
        for sh in bg:
            kill_shell(sh["id"], d)
        interrupt(sid)
        for _ in range(10 if bg else 0):
            time.sleep(0.5)
            if sid in (active() or {}):
                interrupt(sid)
        append(base, id=s["id"], status="reported", note="aborted")
        print(f"{s['id']} aborted -> reported")
        for rname, _, _, nrun in ocq_runs(s):
            if nrun:
                print(f"  note: ocq/{rname} in {d} still has {nrun} running worker(s) (gski ocq abort {rname})")


def register(subparsers):
    p = subparsers.add_parser("ocm", help="manage opencode orchestrator streams")
    sub = p.add_subparsers(dest="ocm_cmd", required=True)

    s = sub.add_parser("start", help="start an orchestrator stream")
    s.add_argument("name")
    s.add_argument("text", help="high-level task for the orchestrator")
    s.add_argument("--dir", help="working directory for the orchestrator (default: cwd)")
    s.add_argument("--model", help="provider/model")
    s.add_argument("--allow", action="append", help="extra allow rule, e.g. 'shell:git *' or 'shell:ssh host *'")
    s.set_defaults(func=cmd_start)

    s = sub.add_parser("ls", help="list orchestrator streams and their ocq runs")
    s.add_argument("--status", nargs="+")
    s.set_defaults(func=cmd_ls)

    s = sub.add_parser("show", help="show stream details and orchestrator's last reply")
    s.add_argument("name")
    s.add_argument("--chars", type=int, default=4000)
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("wait", help="sleep on server events until a running orchestrator stops; low CPU")
    s.add_argument("--timeout", type=int, default=3600)
    s.set_defaults(func=cmd_wait)

    s = sub.add_parser("send", help="message a stream (<name> <text>) or parent manager (.. <text>)")
    s.add_argument("name")
    s.add_argument("text")
    s.add_argument("--queue", action="store_true", help="deliver after the current turn instead of steering")
    s.add_argument("--allow", action="append", help="grant additional allow rule to the session")
    s.set_defaults(func=cmd_send)

    for name, status in (("done", "done"), ("fail", "failed")):
        s = sub.add_parser(name, help=f"mark stream {status}")
        s.add_argument("name")
        s.add_argument("--note")
        s.set_defaults(func=lambda a, st=status: cmd_mark(a, st))

    s = sub.add_parser("abort", help="abort running orchestrator stream(s) -> reported")
    s.add_argument("name", nargs="?")
    s.set_defaults(func=cmd_abort)
