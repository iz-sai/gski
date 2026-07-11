import json
import re
import subprocess
import sys
from pathlib import Path


def _detect_target(target):
    if Path(target).is_file():
        return "file"
    if re.match(r"https?://", target):
        return "url"
    return "search"


def _run_ytdlp(cmd, quiet=False):
    if not quiet:
        print(f"yt-dlp {' '.join(cmd[1:])}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr.strip()
        if err:
            print(f"error: {err}", file=sys.stderr)
    return result.stdout.strip(), result.returncode


def _build_metadata(info):
    return {
        "id": info.get("id"),
        "url": f"https://www.youtube.com/watch?v={info.get('id')}",
        "title": info.get("title"),
        "channel": info.get("channel"),
        "channel_url": info.get("channel_url"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "description": info.get("description"),
        "tags": info.get("tags"),
        "categories": info.get("categories"),
    }


def _extract_comments(info):
    comments = info.get("comments") or []
    return [
        {
            "author": c.get("author"),
            "text": c.get("text"),
            "likes": c.get("like_count", 0),
            "is_reply": c.get("parent") != "root",
        }
        for c in comments
    ]


def _extract_transcript(info):
    subs = info.get("subtitles") or {}
    auto_subs = info.get("automatic_captions") or {}

    for lang in ("en", "en-orig"):
        for source in (subs, auto_subs):
            if lang in source:
                for fmt in source[lang]:
                    if fmt.get("ext") == "json3":
                        return _fetch_subtitle(fmt["url"])
                    if fmt.get("ext") == "vtt":
                        return _fetch_subtitle_vtt(fmt["url"])

    for source in (subs, auto_subs):
        if source:
            first_lang = next(iter(source))
            for fmt in source[first_lang]:
                if fmt.get("ext") == "json3":
                    return _fetch_subtitle(fmt["url"])
                if fmt.get("ext") == "vtt":
                    return _fetch_subtitle_vtt(fmt["url"])

    return None


def _fetch_subtitle(url):
    import urllib.request

    try:
        resp = urllib.request.urlopen(url, timeout=30)
        data = json.loads(resp.read())
        events = data.get("events", [])
        segments = []
        for ev in events:
            segs = ev.get("segs")
            if segs:
                text = "".join(s.get("utf8", "") for s in segs).strip()
                if text:
                    segments.append(text)
        return " ".join(segments)
    except Exception as e:
        print(f"warning: failed to fetch subtitle: {e}", file=sys.stderr)
        return None


def _fetch_subtitle_vtt(url):
    import urllib.request

    try:
        resp = urllib.request.urlopen(url, timeout=30)
        content = resp.read().decode("utf-8")
        lines = []
        for line in content.split("\n"):
            line = line.strip()
            if (
                not line
                or line.startswith("WEBVTT")
                or line.startswith("Kind:")
                or line.startswith("Language:")
            ):
                continue
            if re.match(r"\d{2}:\d{2}", line):
                continue
            if re.match(r"^\d+$", line):
                continue
            line = re.sub(r"<[^>]+>", "", line)
            if line and (not lines or lines[-1] != line):
                lines.append(line)
        return " ".join(lines)
    except Exception as e:
        print(f"warning: failed to fetch subtitle: {e}", file=sys.stderr)
        return None


def _load_archive(path):
    if not path or not Path(path).exists():
        return set()
    return set(Path(path).read_text().strip().split("\n"))


def _save_archive(path, vid_id):
    if not path:
        return
    with open(path, "a") as f:
        f.write(f"{vid_id}\n")


def _download_media(url, args):
    outdir = Path(args.output_dir or ".")
    outdir.mkdir(parents=True, exist_ok=True)
    tmpl = str(outdir / "%(title).180B [%(id)s].%(ext)s")

    cmd = ["yt-dlp", "--no-playlist", "-o", tmpl]

    if args.audio:
        cmd += [
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            str(args.audio_quality),
            "-f",
            "bestaudio/best",
        ]
    elif args.video:
        res = args.res
        cmd += [
            "-f",
            f"bv*[height<={res}]+ba/b[height<={res}]/worst",
        ]

    cmd += ["--print", "after_move:filepath", "--no-simulate", url]

    print(f"downloading {'audio' if args.audio else 'video'}: {url}", file=sys.stderr)
    out, rc = _run_ytdlp(cmd, quiet=True)
    if rc == 0 and out:
        print(f"saved: {out}", file=sys.stderr)
    return rc == 0


def _process_video(url, args, archive=None):
    if archive and url in archive:
        print(f"skip: {url} (archived)", file=sys.stderr)
        return None

    if args.audio or args.video:
        _download_media(url, args)

    cmd = ["yt-dlp", "--dump-json", "--skip-download"]
    if args.comments:
        cmd.append("--write-comments")
    cmd.append(url)

    stdout, rc = _run_ytdlp(cmd)
    if rc != 0 or not stdout:
        return None

    info = json.loads(stdout)
    result = _build_metadata(info)

    if args.comments:
        result["comments"] = _extract_comments(info)

    if args.transcript:
        transcript = _extract_transcript(info)
        if transcript:
            result["transcript"] = transcript

    if args.archive:
        _save_archive(args.archive, info.get("id", url))

    return result


def _process_search(query, args):
    limit = args.limit or 20
    cmd = [
        "yt-dlp",
        f"ytsearch{limit}:{query}",
        "--flat-playlist",
        "--dump-json",
        "--skip-download",
    ]
    stdout, rc = _run_ytdlp(cmd)
    if rc != 0 or not stdout:
        return

    archive = _load_archive(args.archive)

    for line in stdout.strip().split("\n"):
        if not line:
            continue
        info = json.loads(line)
        vid_url = info.get("url") or f"https://www.youtube.com/watch?v={info.get('id')}"

        if args.comments or args.transcript or args.audio or args.video:
            result = _process_video(vid_url, args, archive)
            if result:
                print(json.dumps(result))
                sys.stdout.flush()
        else:
            result = {
                "id": info.get("id"),
                "url": vid_url,
                "title": info.get("title"),
                "channel": info.get("channel"),
                "channel_url": info.get("channel_url"),
                "upload_date": info.get("upload_date"),
                "duration": info.get("duration"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "comment_count": info.get("comment_count"),
                "description": info.get("description"),
            }
            print(json.dumps(result))
            sys.stdout.flush()


def _is_single_video(url):
    return bool(re.match(r"https?://(www\.)?youtube\.com/watch\?v=", url)) or bool(
        re.match(r"https?://youtu\.be/", url)
    )


def _process_url(url, args):
    archive = _load_archive(args.archive)

    if _is_single_video(url):
        result = _process_video(url, args, archive)
        if result:
            print(json.dumps(result))
            sys.stdout.flush()
        return

    cmd = ["yt-dlp", url, "--flat-playlist", "--print", "url"]
    stdout, rc = _run_ytdlp(cmd)
    if rc != 0 or not stdout:
        return

    urls = [l for l in stdout.strip().split("\n") if l and l.startswith("http")]
    if args.limit:
        urls = urls[: args.limit]

    total = len(urls)
    for i, vid_url in enumerate(urls, 1):
        print(f"[{i}/{total}] {vid_url}", file=sys.stderr)
        result = _process_video(vid_url, args, archive)
        if result:
            print(json.dumps(result))
            sys.stdout.flush()
        return

    if len(lines) == 1 and not lines[0].startswith("http"):
        result = _process_video(url, args, archive)
        if result:
            print(json.dumps(result))
            sys.stdout.flush()
        return

    urls = [l for l in lines if l.startswith("http")]
    if args.limit:
        urls = urls[: args.limit]

    total = len(urls)
    for i, vid_url in enumerate(urls, 1):
        print(f"[{i}/{total}] {vid_url}", file=sys.stderr)
        result = _process_video(vid_url, args, archive)
        if result:
            print(json.dumps(result))
            sys.stdout.flush()


def _process_file(filepath, args):
    archive = _load_archive(args.archive)
    urls = [l.strip() for l in Path(filepath).read_text().split("\n") if l.strip()]
    if args.limit:
        urls = urls[: args.limit]

    total = len(urls)
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{total}] {url}", file=sys.stderr)
        result = _process_video(url, args, archive)
        if result:
            print(json.dumps(result))
            sys.stdout.flush()


def _update_ytdlp():
    print("updating yt-dlp...", file=sys.stderr)
    # try yt-dlp self-update first (works for binary/standalone installs)
    r = subprocess.run(["yt-dlp", "-U"], capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    if out:
        print(out, file=sys.stderr)
    if r.returncode == 0 and "pip" not in out.lower() and "not writable" not in out.lower():
        return 0
    # fall back to pip (pip-managed install)
    print("falling back to pip...", file=sys.stderr)
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
        capture_output=True,
        text=True,
    )
    print((r.stdout + r.stderr).strip(), file=sys.stderr)
    if r.returncode == 0:
        v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
        print(f"yt-dlp now at {v.stdout.strip()}", file=sys.stderr)
    return r.returncode


def register(subparsers):
    p = subparsers.add_parser(
        "youtube-scope",
        help="extract data from YouTube — metadata, comments, transcripts",
    )
    p.add_argument(
        "target",
        nargs="?",
        help="video/channel/playlist URL, search query, or file with URLs",
    )
    p.add_argument(
        "--comments",
        action="store_true",
        help="include comments",
    )
    p.add_argument(
        "--transcript",
        action="store_true",
        help="include transcript/subtitles",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max videos to process (for search/channel/playlist)",
    )
    p.add_argument(
        "--archive",
        default=None,
        help="file to track processed video IDs (enables resumability)",
    )
    p.add_argument(
        "--audio",
        action="store_true",
        help="download audio as mp3 (low quality, for inspection)",
    )
    p.add_argument(
        "--video",
        action="store_true",
        help="download low-res video",
    )
    p.add_argument(
        "--res",
        type=int,
        default=360,
        help="max video height when using --video (default 360)",
    )
    p.add_argument(
        "--audio-quality",
        type=int,
        default=9,
        help="mp3 quality 0=best..9=smallest (default 9)",
    )
    p.add_argument(
        "--output-dir",
        default=".",
        help="directory for downloaded media (default current dir)",
    )
    p.add_argument(
        "--update",
        action="store_true",
        help="update yt-dlp to the latest version and exit",
    )
    p.set_defaults(func=run)


def run(args):
    if args.update:
        sys.exit(_update_ytdlp())

    if not args.target:
        print("error: target required (or use --update)", file=sys.stderr)
        sys.exit(1)

    target_type = _detect_target(args.target)

    if target_type == "search":
        _process_search(args.target, args)
    elif target_type == "url":
        _process_url(args.target, args)
    elif target_type == "file":
        _process_file(args.target, args)
