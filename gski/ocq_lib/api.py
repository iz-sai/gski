import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 4096
DEFAULT_DASH_PORT = 4097

BASE_RULES = [
    {"action": "subagent", "resource": "*", "effect": "deny"},
    {"action": "question", "resource": "*", "effect": "deny"},
    {"action": "shell", "resource": "gski ocq*", "effect": "deny"},
]

DEFAULT_CFG = {
    "agent": "worker",
    "model": None,
    "variant": None,
    "concurrency": 1,
    "max_attempts": 3,
    "permission": {},
}

DENY_MSG = "ocq: this specific call is not permitted. Do not retry it; continue without it or write status failed."

_conn = {}


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def _service_file():
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "opencode" / "service.json"


def _read_service():
    try:
        d = json.loads(_service_file().read_text())
        return d["url"].rstrip("/"), d.get("password")
    except (OSError, ValueError, KeyError):
        return None


def _headers(password):
    h = {"content-type": "application/json"}
    if password:
        h["authorization"] = "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()
    return h


def _alive(url, password):
    req = urllib.request.Request(url + "/api/session/active", headers=_headers(password))
    try:
        urllib.request.urlopen(req, timeout=3).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def connect():
    # OCQ_URL (+ OCQ_PASSWORD) targets an explicit server; default is the shared background service
    if _conn:
        return _conn["url"], _conn["password"]
    env = os.environ.get("OCQ_URL")
    if env:
        url, pw = env.rstrip("/"), os.environ.get("OCQ_PASSWORD")
        if not _alive(url, pw):
            die(f"server not reachable at {url}")
    else:
        found = _read_service()
        if not found or not _alive(*found):
            subprocess.run(["opencode", "service", "start"], capture_output=True)
            for _ in range(20):
                found = _read_service()
                if found and _alive(*found):
                    break
                time.sleep(0.5)
            else:
                die("opencode background service not reachable (try: opencode service start)")
        url, pw = found
    _conn.update(url=url, password=pw)
    return url, pw


def _call(method, path, body=None, timeout=60):
    url, pw = connect()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method, headers=_headers(pw))
    with urllib.request.urlopen(req, timeout=timeout) as f:
        raw = f.read()
    return json.loads(raw) if raw else None


def api(method, path, body=None):
    try:
        out = _call(method, path, body)
    except urllib.error.HTTPError as e:
        die(f"http {e.code} {method} {path}: {e.read().decode(errors='replace')[:300]}")
    except (urllib.error.URLError, OSError):
        die("server not reachable (start it: opencode service start)")
    return out.get("data") if isinstance(out, dict) and "data" in out else out


def fetch(path, timeout=5):
    try:
        out = _call("GET", path, timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return out.get("data") if isinstance(out, dict) and "data" in out else out


def parse_model(model):
    # "provider/model#variant" -> (provider, model, variant)
    if not model:
        return None, None, None
    model, _, variant = model.partition("#")
    prov, _, mid = model.partition("/")
    return prov, mid, variant or None


def _retry(fn, tries=20):
    # the service may still be loading providers right after a restart
    for _ in range(tries):
        out = fn()
        if out:
            return out
        time.sleep(0.5)
    return None


def resolve_model(agent, model, variant):
    # precedence: explicit model > agent's own model > server default
    prov, mid, var = parse_model(model)
    src = "run"
    if not mid:
        src = "agent"
        info = _retry(lambda: next((a for a in fetch("/api/agent") or [] if a.get("id") == agent), None))
        if not info:
            die(f"unknown agent: {agent}")
        m = info.get("model") or {}
        prov, mid = m.get("providerID"), m.get("id")
    if not mid:
        src = "default"
        d = _retry(lambda: fetch("/api/model/default")) or {}
        prov, mid = d.get("providerID"), d.get("modelID") or d.get("id")
    if not mid:
        die("cannot resolve a model: set --model or a default model")
    return {"providerID": prov, "id": mid, **({"variant": variant or var} if (variant or var) else {})}, src


def fmt_model(ref):
    return f"{ref['providerID']}/{ref['id']}" + (f"#{ref['variant']}" if ref.get("variant") else "")


def create_session(title, agent, model, variant, rules, directory):
    ref, src = resolve_model(agent, model, variant)
    body = {"title": title, "agent": agent, "permissions": rules, "location": {"directory": directory}, "model": ref}
    s = api("POST", "/api/session", body)
    got = s.get("model") or {}
    if (got.get("providerID"), got.get("id")) != (ref["providerID"], ref["id"]):
        die(f"server did not apply model {fmt_model(ref)} (got {fmt_model(got) if got else 'none'})")
    return s, f"{fmt_model(ref)} ({src})"


def send_prompt(sid, text):
    return api("POST", f"/api/session/{sid}/prompt", {"text": text})


def messages(sid, limit=None, timeout=60):
    q = f"?limit={limit}" if limit else ""
    return fetch(f"/api/session/{sid}/message{q}", timeout=timeout) or []


def session_info(sid):
    return fetch(f"/api/session/{sid}") or {}


def active():
    return fetch("/api/session/active")


def interrupt(sid):
    api("POST", f"/api/session/{sid}/interrupt")


def assistants(msgs):
    return [m for m in msgs if m.get("type") == "assistant"]


def last_text(msgs):
    for m in assistants(msgs):
        txt = "\n".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text").strip()
        if txt:
            return txt
    return ""


def err_text(err):
    if not isinstance(err, dict):
        return str(err)
    return f"{err.get('type') or err.get('name') or 'error'}: {err.get('message', '')}".strip(": ")


def sweep(rd, cfg, by_session, append_fn):
    for sid, tid in by_session.items():
        for p in fetch(f"/api/session/{sid}/permission") or []:
            api("POST", f"/api/session/{sid}/permission/{p['id']}/reply", {"decision": "reject", "message": DENY_MSG})
            what = f"{p.get('action')}: {' '.join(p.get('resources') or [])}"[:120]
            append_fn(rd, id=tid, denied=what)
            print(f"{tid} denied {what}")


def activity(msgs):
    for m in assistants(msgs):
        for c in reversed(m.get("content", [])):
            if c.get("type") == "tool":
                inp = (c.get("state") or {}).get("input") or {}
                what = inp.get("command") or inp.get("path") or inp.get("filePath") or inp.get("pattern") or ""
                return f"{c.get('name')}: {what}"[:200]
            if c.get("type") == "text" and c.get("text", "").strip():
                return c["text"][:200]
    return ""
