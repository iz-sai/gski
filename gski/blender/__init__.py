import json
import math
import os
from pathlib import Path
import socket
import sys


def register(subparsers):
    parser = subparsers.add_parser("blender", help="control a live Blender UI session")
    parser.add_argument("--pid", type=int, help="Blender process to connect to")
    parser.add_argument("--timeout", type=float, default=30)
    commands = parser.add_subparsers(dest="blender_command", required=True)
    commands.add_parser("info", help="show file, frame, camera and selection")
    execute = commands.add_parser("exec", help="execute a Python file or -c code inside Blender")
    execute.add_argument("file", type=Path, nargs="?")
    execute.add_argument("-c", "--code", help="Python code to run instead of a file")
    capture = commands.add_parser("capture", help="render small camera PNGs for review")
    capture.add_argument("output", type=Path)
    capture.add_argument("--frame", type=int, nargs="+")
    capture.add_argument("--width", type=int, default=960)
    parser.set_defaults(func=run)


def runtime_dir():
    base = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    return base / f"gski-blender-{os.getuid()}"


def live_session():
    live = []
    for path in sorted(runtime_dir().glob("*.sock")):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            try:
                probe.connect(str(path))
                live.append(path)
            except ConnectionRefusedError:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    if not live:
        raise SystemExit("No live Blender session")
    if len(live) > 1:
        raise SystemExit(f"Several sessions ({', '.join(p.stem for p in live)}); pass --pid")
    return live[0]


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


def capture_targets(args):
    output = args.output.expanduser().resolve()
    if not output.parent.is_dir() or output.suffix.lower() != ".png":
        raise SystemExit("Use a .png path in an existing output directory")
    if not 64 <= args.width <= 1920:
        raise SystemExit("Capture width must be between 64 and 1920")
    frames = args.frame or [None]
    if len(frames) > 12:
        raise SystemExit("Capture at most 12 frames per call")
    if len(frames) == 1:
        return [(frames[0], str(output))]
    return [(f, str(output.with_name(f"{output.stem}_{f:04d}.png"))) for f in frames]


def stitch(targets, output):
    from PIL import Image, ImageDraw, ImageFont
    images = []
    for frame, path in targets:
        with Image.open(path) as image:
            images.append((frame, image.convert("RGB")))
    n, (w, h) = len(images), images[0][1].size
    def score(c):
        r = math.ceil(n / c)
        return abs(math.log(c * w / (r * h))) + (c * r - n) / n
    cols = min(range(1, n + 1), key=score)
    rows = math.ceil(n / cols)
    scale = min(1, 1600 / (cols * w), 1600 / (rows * h))
    tile_w, tile_h, gap = round(w * scale), round(h * scale), 4
    grid = Image.new("RGB", (cols * tile_w + (cols - 1) * gap, rows * tile_h + (rows - 1) * gap))
    draw = ImageDraw.Draw(grid)
    font = ImageFont.load_default(size=max(14, tile_w // 16))
    for index, (frame, image) in enumerate(images):
        x, y = index % cols * (tile_w + gap), index // cols * (tile_h + gap)
        grid.paste(image.resize((tile_w, tile_h)), (x, y))
        box = draw.textbbox((x + 6, y + 4), f"f{frame}", font=font)
        draw.rectangle((box[0] - 4, box[1] - 2, box[2] + 4, box[3] + 2), fill="black")
        draw.text((x + 6, y + 4), f"f{frame}", font=font, fill="white")
    grid.save(output)


def capture_code(args, targets):
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
    render.engine = 'BLENDER_WORKBENCH'
    render.resolution_y = max(1, round({args.width} * saved[4] / saved[3]))
    render.resolution_x = {args.width}
    render.resolution_percentage = 100
    render.threads_mode = 'FIXED'
    render.threads = 2
    render.image_settings.file_format = 'PNG'
    render.use_file_extension = False
    for frame, path in {targets!r}:
        if frame is not None:
            scene.frame_set(frame)
        render.filepath = path
        bpy.ops.render.render(write_still=True)
finally:
    (frame, subframe, render.engine, render.resolution_x, render.resolution_y,
     render.resolution_percentage, render.filepath, render.image_settings.file_format,
     render.use_file_extension, render.threads_mode, render.threads) = saved
    scene.frame_set(frame, subframe=subframe)
"""


def print_info(info):
    path = Path(info["file"]) if info["file"] else None
    if path and path.is_relative_to(Path.cwd()):
        path = path.relative_to(Path.cwd())
    print(f"{path or '(new file)'}" + ("  (unsaved)" if info["dirty"] else ""))
    line = f"frame {info['frame']} [{info['range'][0]}-{info['range'][1]}]"
    line += f"  camera {info['camera'] or 'none'}"
    if info["selected"]:
        line += f"  selected {', '.join(info['selected'])}"
    if info["scene"] != "Scene":
        line += f"  scene {info['scene']}"
    print(line)


def run(args):
    path = runtime_dir() / f"{args.pid}.sock" if args.pid else live_session()
    targets = capture_targets(args) if args.blender_command == "capture" else None
    if args.blender_command == "info":
        payload = {"op": "info"}
    elif targets:
        payload = {"op": "exec", "code": capture_code(args, targets)}
    else:
        if (args.code is None) == (args.file is None):
            raise SystemExit("exec needs either a FILE or -c CODE")
        code = args.code if args.code is not None else args.file.expanduser().read_text()
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
        error = response.get("error", "Unknown Blender error")
        start = error.find('  File "<gski-blender>"')
        print(error[start:] if start >= 0 else error, file=sys.stderr, end="")
        raise SystemExit(1)
    if args.blender_command == "info":
        print_info(response)
    elif targets and len(targets) > 1:
        output = args.output.expanduser().resolve()
        stitch(targets, output.with_name(f"{output.stem}_grid.png"))
