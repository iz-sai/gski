import json
import os
import re
import time
from pathlib import Path

from gski.ocq_lib.api import DEFAULT_CFG, die

WIDTH = 160
RUN_RE = re.compile(r"^[\w.-]+$")
PARENT_TARGETS = ("..", "orchestrator", "parent")
REGISTRY = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "ocq" / "projects"
ACTIONS = {"bash": "shell", "task": "subagent", "write": "edit", "patch": "edit"}


def cut(s, n=WIDTH):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def project_root():
    cwd = Path.cwd()
    for d in [cwd, *cwd.parents]:
        if (d / ".ocq").is_dir():
            return d
    return cwd


def known_projects():
    return [line for line in REGISTRY.read_text().splitlines() if line] if REGISTRY.exists() else []


def remember(root):
    root = str(root)
    if root not in known_projects():
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY, "a") as f:
            f.write(root + "\n")


def touch_orchestrator(rd):
    sid = os.environ.get("OPENCODE_SESSION_ID")
    if not sid:
        return
    cfg_path = rd / "run.json"
    if not cfg_path.exists():
        return
    if any(t.get("session") == sid for t in fold(rd).values()):
        return
    try:
        cfg = json.loads(cfg_path.read_text())
        if cfg.get("orchestrator") != sid:
            cfg["orchestrator"] = sid
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    except Exception:
        pass


def ensure_run(run, allow=None):
    if run in PARENT_TARGETS or not RUN_RE.match(run):
        die(f"invalid run name: {run}")
    root = project_root()
    base = root / ".ocq"
    base.mkdir(exist_ok=True)
    gi = base / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n")
    rd = base / "runs" / run
    (rd / "results").mkdir(parents=True, exist_ok=True)
    cfg_path = rd / "run.json"
    cfg = {**DEFAULT_CFG, **(json.loads(cfg_path.read_text()) if cfg_path.exists() else {})}
    cfg["dir"] = str(root)
    sid = os.environ.get("OPENCODE_SESSION_ID")
    if sid and not any(t.get("session") == sid for t in fold(rd).values()):
        cfg["orchestrator"] = sid
    if allow:
        cfg["allow"] = list(dict.fromkeys((cfg.get("allow") or []) + list(allow)))
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    remember(root)
    return rd, cfg


def run_dir(run, must=True):
    rd = project_root() / ".ocq" / "runs" / run
    if must and not (rd / "run.json").exists():
        die(f"run not found: {rd}")
    touch_orchestrator(rd)
    return rd


def load_cfg(rd):
    return {**DEFAULT_CFG, **json.loads((rd / "run.json").read_text())}


def append(rd, **ev):
    p = rd / "ledger.jsonl"
    with open(p, "ab+") as f:
        f.seek(0, os.SEEK_END)
        if f.tell():
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write((json.dumps({"t": int(time.time()), **ev}, ensure_ascii=False) + "\n").encode())


def sum_tokens(items):
    out = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    for tk in items:
        if not tk:
            continue
        cache = tk.get("cache") or {}
        out["input"] += tk.get("input", 0) or 0
        out["output"] += tk.get("output", 0) or 0
        out["reasoning"] += tk.get("reasoning", 0) or 0
        out["cache_read"] += tk.get("cache_read", cache.get("read", 0)) or 0
        out["cache_write"] += tk.get("cache_write", cache.get("write", 0)) or 0
    return out


def fold(rd):
    tasks = {}
    p = rd / "ledger.jsonl"
    if not p.exists():
        return tasks
    for line in p.read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = tasks.setdefault(ev["id"], {"id": ev["id"], "attempts": 0})
        t["updated"] = ev.pop("t", None)
        denied = ev.pop("denied", None)
        if denied:
            t.setdefault("denied", []).append(denied)
        t["cost"] = round(t.get("cost", 0) + (ev.pop("cost", 0) or 0), 4)
        tk = ev.pop("tokens", None)
        if tk:
            t["tokens"] = sum_tokens([t.get("tokens"), tk])
        t.update(ev)
    return tasks


def resolve(tasks, ids):
    out = []
    for i in ids:
        tid = i if i in tasks else i.zfill(4)
        if tid not in tasks:
            die(f"unknown task: {i}")
        out.append(tid)
    return out


def rules_from(perm):
    rules = []
    for key, val in (perm or {}).items():
        act = ACTIONS.get(key, key)
        if isinstance(val, str):
            rules.append({"action": act, "resource": "*", "effect": val})
        else:
            rules += [{"action": act, "resource": pat, "effect": eff} for pat, eff in val.items()]
    return rules


def parse_allow(spec):
    key, _, pat = spec.partition(":")
    key = key.strip()
    return {"action": ACTIONS.get(key, key), "resource": pat.strip() or "*", "effect": "allow"}


def build_prompt(rd, run, t):
    rel = f".ocq/runs/{run}"
    parts = [f"ocq run: {run}  task: {t['id']}"]
    brief = rd / "brief.md"
    if brief.exists() and brief.read_text().strip():
        parts.append(f"Read the brief first: {rel}/brief.md")
    parts += [
        "",
        "Task:",
        t["task"],
        "",
        "No human is available. Stay in scope; if blocked with no background jobs to keep alive, report failed with reason and partial work.",
        "No extra tests, paranoid syntax checks, or validation unless asked in the brief or task. Observe execution errors; done means execution completed.",
        'To message orchestrator while keeping work/background jobs running: gski ocq send .. "..."',
        "",
        f"When finished, write {rel}/results/{t['id']}.json:",
        '{"status": "done" | "failed", "artifact": "<path or short value>", "note": "<one line>"}',
        "Then reply with one line.",
    ]
    return "\n".join(parts)


def short_model(t):
    m = (t.get("model") or "").split("/")[-1].split("#")[0].replace("gemini-4-", "")
    a = t.get("agent")
    if a and a != "worker" and m:
        return f" [{a}/{m}]"
    if m and m != "hydrogen":
        return f" [{m}]"
    if a and a != "worker":
        return f" [{a}]"
    return ""


def summary(tasks):
    counts = {}
    for t in tasks.values():
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    cost = sum(t.get("cost") or 0 for t in tasks.values())
    order = ["running", "done", "failed", "reported", "pending"]
    parts = [f"{s} {counts[s]}" for s in order if counts.get(s)]
    return f"{len(tasks)} tasks: " + (", ".join(parts) or "empty") + f" | cost ${cost:.2f}"


def row(t):
    if t["status"] in ("done", "failed", "reported"):
        prefix = f"{t['worker']} " if t["status"] == "reported" and t.get("worker") else ""
        info = f"{prefix}{t.get('artifact') or '-'} | {t.get('note') or ''}"
    elif t["status"] == "running" and t.get("msg"):
        info = f"msg: {t['msg']}"
    else:
        info = t.get("task", "")
    denied = f" [denied {len(t['denied'])}]" if t.get("denied") else ""
    att = f" a{t['attempts']}" if (t.get("attempts") or 0) > 1 else ""
    return cut(f"{t['id']} {t['status']}{short_model(t)}{att}{denied} {info}")
