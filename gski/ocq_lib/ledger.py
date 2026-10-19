import json
import os
import sys
import time
from pathlib import Path

from gski.ocq_lib.api import DEFAULT_CFG, die

WIDTH = 160
SHOW = ("running", "reported", "failed")
REGISTRY = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "ocq" / "projects"


def cut(s, n=WIDTH):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def project_root():
    cwd = Path.cwd()
    for d in [cwd, *cwd.parents]:
        if (d / ".ocq").is_dir():
            return d
    return cwd


def run_dir(run, must=True):
    rd = project_root() / ".ocq" / "runs" / run
    if must and not (rd / "run.json").exists():
        die(f"run not found: {rd}")
    return rd


def known_projects():
    return [line for line in REGISTRY.read_text().splitlines() if line] if REGISTRY.exists() else []


def remember(root):
    root = str(root)
    if root not in known_projects():
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY, "a") as f:
            f.write(root + "\n")


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


ACTIONS = {"bash": "shell", "task": "subagent", "write": "edit", "patch": "edit"}


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


def build_prompt(run, t):
    rel = f".ocq/runs/{run}"
    parts = [
        f"ocq run: {run}  task: {t['id']}  attempt: {t['attempts']}",
        f"Read the brief first: {rel}/brief.md",
        "",
        "Task:",
        t["task"],
    ]
    if t.get("feedback"):
        parts += ["", "Feedback on the previous attempt:", t["feedback"]]
    parts += [
        "",
        f"When finished, write {rel}/results/{t['id']}.json:",
        '{"status": "done" | "failed", "artifact": "<path or short value>", "note": "<one line>"}',
        "Then reply with one line.",
    ]
    return "\n".join(parts)


def summary(tasks):
    counts = {}
    for t in tasks.values():
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    cost = sum(t.get("cost") or 0 for t in tasks.values())
    order = ["pending", "running", "reported", "done", "failed"]
    parts = [f"{s} {counts[s]}" for s in order if counts.get(s)]
    return f"{len(tasks)} tasks: " + (", ".join(parts) or "empty") + f" | cost ${cost:.2f}"


def row(t):
    if t["status"] in ("reported", "done", "failed") and t.get("worker"):
        info = f"{t['worker']} {t.get('artifact') or '-'} | {t.get('note') or ''}"
    else:
        info = t.get("task", "")
    extra = f" [denied {len(t['denied'])}]" if t.get("denied") else ""
    return cut(f"{t['id']} {t['status']} a{t.get('attempts', 0)}{extra} {info}")
