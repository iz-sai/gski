import json
import os
from pathlib import Path
import socket
import sys


def register(subparsers):
    parser = subparsers.add_parser("blender", help="control a live Blender UI session")
    parser.add_argument("--pid", type=int, help="Blender process to connect to")
    parser.add_argument("--timeout", type=float, default=30)
    commands = parser.add_subparsers(dest="blender_command", required=True)
    commands.add_parser("sessions", help="list socket paths (may include stale sessions)")
    commands.add_parser("info", help="inspect the connected scene")
    execute = commands.add_parser("exec", help="execute a Python file inside Blender")
    execute.add_argument("file", type=Path)
    capture = commands.add_parser("capture", help="render a small camera PNG for review")
    capture.add_argument("output", type=Path)
    capture.add_argument("--frame", type=int)
    capture.add_argument("--width", type=int, default=960)
    parser.set_defaults(func=run)


def runtime_dir():
    base = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    return base / f"gski-blender-{os.getuid()}"


def request(path, payload, timeout):
    data = json.dumps(payload).encode() + b"\n"
    if len(data) > 1048576:
        raise SystemExit("Command exceeds 1 MiB")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(data)
        response = bytearray()
        while b"\n" not in response:
            chunk = connection.recv(65536)
            if not chunk:
                raise RuntimeError("Blender disconnected without a response")
            response.extend(chunk)
            if len(response) > 2097152:
                raise RuntimeError("Blender response exceeds 2 MiB")
    return json.loads(response)


def capture_code(args):
    output = args.output.expanduser().resolve()
    if not output.parent.is_dir() or output.suffix.lower() != ".png":
        raise SystemExit("Use a .png path in an existing output directory")
    if not 64 <= args.width <= 1920:
        raise SystemExit("Capture width must be between 64 and 1920")
    return f"""import bpy
scene = bpy.context.scene
if scene.camera is None:
    raise RuntimeError('Scene has no active camera')
render = scene.render
saved = (scene.frame_current, scene.frame_subframe, render.engine,
         render.resolution_x, render.resolution_y, render.resolution_percentage,
         render.filepath, render.image_settings.file_format, render.use_file_extension,
         render.threads_mode, render.threads)
try:
    frame = {args.frame!r}
    if frame is not None:
        scene.frame_set(frame)
    render.engine = 'BLENDER_WORKBENCH'
    render.resolution_y = max(1, round({args.width} * saved[4] / saved[3]))
    render.resolution_x = {args.width}
    render.resolution_percentage = 100
    render.threads_mode = 'FIXED'
    render.threads = 2
    render.filepath = {str(output)!r}
    render.image_settings.file_format = 'PNG'
    render.use_file_extension = True
    bpy.ops.render.render(write_still=True)
    print(render.filepath)
finally:
    (frame, subframe, render.engine, render.resolution_x, render.resolution_y,
     render.resolution_percentage, render.filepath, render.image_settings.file_format,
     render.use_file_extension, render.threads_mode, render.threads) = saved
    scene.frame_set(frame, subframe=subframe)
"""


def run(args):
    paths = sorted(runtime_dir().glob("*.sock"))
    if args.blender_command == "sessions":
        for path in paths:
            print(f"{path.stem}\t{path}")
        return
    if args.pid is not None:
        path = runtime_dir() / f"{args.pid}.sock"
    elif len(paths) == 1:
        path = paths[0]
    else:
        raise SystemExit("Choose a session with --pid; list them with gski blender sessions")
    if args.blender_command == "info":
        payload = {"op": "info"}
    else:
        code = (args.file.expanduser().read_text() if args.blender_command == "exec"
                else capture_code(args))
        payload = {"op": "exec", "code": code}
    try:
        response = request(path, payload, args.timeout)
    except TimeoutError:
        raise SystemExit("Timed out; Blender may still be executing. Do not blindly retry.")
    except OSError as error:
        raise SystemExit(f"Cannot connect to Blender: {error}")
    if response.get("output"):
        print(response["output"], end="")
    if not response.get("ok"):
        print(response.get("error", "Unknown Blender error"), file=sys.stderr)
        raise SystemExit(1)
    if "scene" in response:
        print(json.dumps(response, indent=2, ensure_ascii=False))
