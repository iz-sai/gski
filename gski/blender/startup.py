import atexit
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import time
import traceback

import bpy


_server = None
_path = None
_clients = {}


def execute(payload):
    if payload.get("op") == "info":
        scene = bpy.context.scene
        return {
            "ok": True, "pid": os.getpid(), "file": bpy.data.filepath,
            "dirty": bpy.data.is_dirty, "scene": scene.name,
            "frame": scene.frame_current, "range": [scene.frame_start, scene.frame_end],
            "camera": scene.camera.name if scene.camera else None,
            "selected": [obj.name for obj in bpy.context.selected_objects],
        }
    if payload.get("op") != "exec" or not isinstance(payload.get("code"), str):
        raise ValueError("Expected info or exec with Python code")
    output = io.StringIO()
    response = {"ok": True}
    try:
        with redirect_stdout(output), redirect_stderr(output):
            namespace = {"bpy": bpy, "__name__": "__gski_live__"}
            exec(compile(payload["code"], "<gski-blender>", "exec"), namespace)
    except BaseException:
        response = {"ok": False, "error": traceback.format_exc()[-16000:]}
    response["output"] = output.getvalue()[-64000:]
    for screen in bpy.data.screens:
        for area in screen.areas:
            area.tag_redraw()
    return response


def close_client(connection):
    _clients.pop(connection, None)
    connection.close()


def tick():
    if _server is None:
        return None
    for _ in range(4):
        try:
            connection, _ = _server.accept()
        except BlockingIOError:
            break
        connection.setblocking(False)
        if len(_clients) >= 8:
            connection.close()
        else:
            _clients[connection] = {"input": bytearray(), "output": None,
                                    "deadline": time.monotonic() + 10}
    for connection, state in list(_clients.items()):
        if time.monotonic() > state["deadline"]:
            close_client(connection)
            continue
        try:
            if state["output"] is None:
                chunk = connection.recv(65536)
                if not chunk:
                    close_client(connection)
                    continue
                state["input"].extend(chunk)
                if len(state["input"]) > 1048576:
                    close_client(connection)
                    continue
                if b"\n" not in state["input"]:
                    continue
                try:
                    payload = json.loads(state["input"].split(b"\n", 1)[0])
                    response = execute(payload)
                except Exception:
                    response = {"ok": False, "error": traceback.format_exc()[-16000:]}
                state["output"] = json.dumps(response).encode() + b"\n"
                state["deadline"] = time.monotonic() + 10
            sent = connection.send(state["output"])
            state["output"] = state["output"][sent:]
            if not state["output"]:
                close_client(connection)
        except BlockingIOError:
            continue
        except OSError:
            close_client(connection)
    return 0.1


def unregister():
    global _server, _path
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    for connection in list(_clients):
        close_client(connection)
    if _server is not None:
        _server.close()
        _server = None
    if _path is not None:
        _path.unlink(missing_ok=True)
        _path = None


def register():
    global _server, _path
    if bpy.app.background or _server is not None:
        return
    directory = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / f"gski-blender-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise RuntimeError(f"Unsafe socket directory: {directory}")
    directory.chmod(0o700)
    path = directory / f"{os.getpid()}.sock"
    if path.exists():
        raise RuntimeError(f"Bridge socket already exists: {path}")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        path.chmod(0o600)
        server.listen(8)
        server.setblocking(False)
    except Exception:
        server.close()
        raise
    _server, _path = server, path
    bpy.app.timers.register(tick, first_interval=0.5, persistent=True)
    atexit.register(unregister)
    print(f"gski Blender bridge: {path}")


if __name__ == "__main__":
    register()
