import shutil
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).parent / "ctx_tui" / "cli.ts"


def register(subparsers):
    p = subparsers.add_parser("ctx", help="mark parts of the current session for cleanup (applied in the TUI)")
    p.add_argument("--session", help="session id (default: $OPENCODE_SESSION_ID)")
    sub = p.add_subparsers(dest="ctx_cmd", required=True)

    ls = sub.add_parser("list", help="list cleanup candidates, largest first")
    ls.add_argument("--limit", type=int, default=40)
    ls.add_argument("--min", type=int, default=200, help="min size in tokens")
    ls.add_argument("--seq", action="store_true", help="chronological order")

    mk = sub.add_parser("mark", help="mark items: <id>:<strip|truncate|delete> ...")
    mk.add_argument("marks", nargs="*")
    mk.add_argument("--clear", action="store_true", help="discard the plan")

    sub.add_parser("plan", help="show the pending plan")
    p.set_defaults(func=run)


def run(args):
    bun = shutil.which("bun")
    if not bun:
        print("error: bun not found", file=sys.stderr)
        sys.exit(1)
    cmd = [bun, str(CLI)]
    if args.session:
        cmd += ["--session", args.session]
    cmd.append(args.ctx_cmd)
    if args.ctx_cmd == "list":
        cmd += ["--limit", str(args.limit), "--min", str(args.min)]
        if args.seq:
            cmd.append("--seq")
    elif args.ctx_cmd == "mark":
        cmd += args.marks
        if args.clear:
            cmd.append("--clear")
    sys.exit(subprocess.run(cmd).returncode)
