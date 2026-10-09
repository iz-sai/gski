import json
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gski.ocq_lib.api import DEFAULT_DASH_PORT, activity, active, fetch, last_text, messages, session_info
from gski.ocq_lib.ledger import cut, fold, known_projects, project_root, remember, sum_tokens

WEB_DIR = Path(__file__).parent / "web"
RUN_RE = re.compile(r"^[\w.-]+$")
DONE_TOKENS = {}


def seed():
    for s in fetch("/api/session?search=ocq/&limit=2000", timeout=15) or []:
        d = (s.get("location") or {}).get("directory")
        if d and str(s.get("title", "")).startswith("ocq/") and (Path(d) / ".ocq" / "runs").is_dir():
            remember(d)
    root = project_root()
    if (root / ".ocq" / "runs").is_dir():
        remember(root)


def runs_of(root):
    base = Path(root) / ".ocq" / "runs"
    return [p for p in base.iterdir() if (p / "run.json").exists()] if base.is_dir() else []


def mtime(rd):
    p = rd / "ledger.jsonl"
    return int((p if p.exists() else rd / "run.json").stat().st_mtime)


def run_info(rd, tasks=None):
    tasks = fold(rd) if tasks is None else tasks
    try:
        cfg = json.loads((rd / "run.json").read_text())
    except (ValueError, OSError):
        cfg = {}
    counts = {}
    for t in tasks.values():
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    return {
        "name": rd.name,
        "counts": counts,
        "total": len(tasks),
        "cost": round(sum(t.get("cost") or 0 for t in tasks.values()), 4),
        "last": mtime(rd),
        "agent": cfg.get("agent"),
        "model": cfg.get("model"),
        "concurrency": cfg.get("concurrency"),
    }


def projects():
    out = []
    for root in known_projects():
        rds = runs_of(root)
        if not rds:
            continue
        infos = [run_info(rd) for rd in rds]
        out.append({
            "path": root,
            "name": Path(root).name or root,
            "runs": len(infos),
            "last": max(i["last"] for i in infos),
            "running": sum(i["counts"].get("running", 0) for i in infos),
        })
    return sorted(out, key=lambda p: -p["last"])


def project(root):
    return sorted((run_info(rd) for rd in runs_of(root)), key=lambda r: -r["last"])


def live_info(sid, root):
    s = session_info(sid)
    return {
        "cost": round(s.get("cost") or 0, 4),
        "tokens": s.get("tokens"),
        "activity": activity(messages(sid, limit=4)),
        "todos": None,
    }


def finished_tokens(sid, root):
    if sid not in DONE_TOKENS:
        s = fetch(f"/api/session/{sid}")
        if s is None:
            return None
        DONE_TOKENS[sid] = sum_tokens([s.get("tokens")])
    return DONE_TOKENS[sid]


def run_detail(root, name):
    rd = Path(root) / ".ocq" / "runs" / name
    tasks = fold(rd)
    live = active()
    brief = rd / "brief.md"
    rows = []
    for t in tasks.values():
        r = {
            "id": t["id"],
            "status": t["status"],
            "attempts": t.get("attempts", 0),
            "worker": t.get("worker"),
            "artifact": t.get("artifact"),
            "note": cut(t.get("note"), 300),
            "task": cut(t.get("task"), 300),
            "started": t.get("started"),
            "finished": t.get("finished"),
            "updated": t.get("updated"),
            "cost": t.get("cost") or 0,
            "denied": len(t.get("denied") or []),
            "live": None,
            "tokens": t.get("tokens"),
        }
        if t["status"] == "running" and live is not None:
            r["live"] = "busy" if t.get("session") in live else "idle"
            info = live_info(t["session"], root)
            r["cost"] = round(r["cost"] + info.pop("cost"), 4)
            r["tokens"] = sum_tokens([r["tokens"], info.pop("tokens")])
            r.update(info)
        elif not r["tokens"] and t.get("session") and t["status"] != "pending" and live is not None:
            r["tokens"] = finished_tokens(t["session"], root)
        rows.append(r)
    info = run_info(rd, tasks)
    info["cost"] = round(sum(r["cost"] for r in rows), 4)
    info["tokens"] = sum_tokens(r["tokens"] for r in rows)
    return {
        **info,
        "server": live is not None,
        "brief": brief.read_text()[:6000] if brief.exists() else "",
        "tasks": rows,
    }


def task_detail(root, name, tid):
    rd = Path(root) / ".ocq" / "runs" / name
    t = fold(rd).get(tid)
    if not t:
        return None
    reply = ""
    if t.get("session"):
        reply = last_text(messages(t["session"], timeout=10))[:4000]
    keys = ("id", "status", "attempts", "task", "worker", "artifact", "note", "feedback", "denied", "session", "cost", "tokens")
    d = {k: t.get(k) for k in keys}
    if t.get("session") and t["status"] == "running":
        s = session_info(t["session"])
        d["tokens"] = sum_tokens([d["tokens"], s.get("tokens")])
    elif t.get("session") and not d["tokens"]:
        d["tokens"] = finished_tokens(t["session"], root)
    return {**d, "reply": reply}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        if isinstance(body, (bytes, bytearray)):
            data = body
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}

        if u.path == "/":
            return self.send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path == "/style.css":
            return self.send(200, (WEB_DIR / "style.css").read_bytes(), "text/css; charset=utf-8")
        if u.path == "/app.js":
            return self.send(200, (WEB_DIR / "app.js").read_bytes(), "text/javascript; charset=utf-8")
        if u.path == "/api/projects":
            return self.send(200, {"server": active() is not None, "projects": projects()})

        root = q.get("path")
        if root not in known_projects():
            return self.send(404, {"error": "unknown project"})
        if u.path == "/api/project":
            return self.send(200, project(root))

        run = q.get("run", "")
        if not RUN_RE.match(run) or not (Path(root) / ".ocq" / "runs" / run / "run.json").exists():
            return self.send(404, {"error": "unknown run"})
        if u.path == "/api/run":
            return self.send(200, run_detail(root, run))
        if u.path == "/api/task":
            d = task_detail(root, run, q.get("id", ""))
            return self.send(200, d) if d else self.send(404, {"error": "unknown task"})

        self.send(404, {"error": "not found"})


def run(args):
    seed()
    port = getattr(args, "port", DEFAULT_DASH_PORT)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"ocq dash on http://127.0.0.1:{port}", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
