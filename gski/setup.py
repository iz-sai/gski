import shutil
import sys
from importlib.resources import files
from pathlib import Path


def register(subparsers):
    p = subparsers.add_parser("setup", help="symlink skill folders to target directory")
    p.add_argument(
        "target_dir", help="directory to link skills into (e.g. ~/.config/opencode/skills)"
    )
    p.add_argument(
        "--copy", action="store_true", help="copy files instead of symlinking folders"
    )
    p.set_defaults(func=run)


def run(args):
    skills_dir = files("gski") / "skills"
    target = Path(args.target_dir).expanduser()
    target.mkdir(parents=True, exist_ok=True)

    count = 0
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        src = Path(skill_dir).resolve()
        dest = target / skill_name

        if args.copy:
            if dest.is_symlink():
                dest.unlink()
            dest.mkdir(parents=True, exist_ok=True)
            for f in skill_dir.iterdir():
                dst = dest / f.name
                dst.write_text(f.read_text())
                count += 1
                print(f"  {dst}")
        else:
            if dest.is_symlink():
                dest.unlink()
            elif dest.is_dir():
                shutil.rmtree(dest)
            elif dest.exists():
                dest.unlink()
            dest.symlink_to(src)
            count += 1
            print(f"  {dest} -> {src}")

    if count == 0:
        print("no skills found", file=sys.stderr)
        sys.exit(1)

    action = "copied" if args.copy else "linked"
    unit = "file(s)" if args.copy else "skill(s)"
    print(f"\n{count} {unit} {action} in {target}")
