import json
import re
import sys
from pathlib import Path


def _resolve_path(target):
    p = Path(target).expanduser()
    if p.is_dir():
        cand = p / "result.json"
        if cand.is_file():
            return cand
        print(f"error: no result.json in {p}", file=sys.stderr)
        sys.exit(1)
    if p.is_file():
        return p
    print(f"error: path not found: {target}", file=sys.stderr)
    sys.exit(1)


def _load(target):
    path = _resolve_path(target)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _msg_text(m):
    te = m.get("text_entities")
    if te:
        return "".join(e.get("text", "") for e in te)
    t = m.get("text")
    if isinstance(t, str):
        return t
    if isinstance(t, list):
        return "".join(p if isinstance(p, str) else p.get("text", "") for p in t)
    return ""


def _total_reactions(m):
    return sum(r.get("count", 0) for r in (m.get("reactions") or []))


def _media_kind(m):
    if m.get("media_type"):
        return m["media_type"]
    if m.get("photo"):
        return "photo"
    if m.get("poll"):
        return "poll"
    if m.get("file"):
        return "file"
    return None


def _date(m):
    return (m.get("date") or "")


def _in_date_range(m, since, until):
    d = _date(m)[:10]
    if since and d < since:
        return False
    if until and d > until:
        return False
    return True


def _collapse(s):
    return re.sub(r"\s+", " ", s).strip()


def _snippet(text, match, width):
    text = _collapse(text)
    if len(text) <= width:
        return text
    if match is None:
        return text[:width] + "…"
    start = max(0, match.start() - width // 3)
    end = min(len(text), start + width)
    chunk = text[start:end]
    if start > 0:
        chunk = "…" + chunk
    if end < len(text):
        chunk = chunk + "…"
    return chunk


# ---------------------------------------------------------------------------
# subcommands


def cmd_info(args):
    data = _load(args.path)
    msgs = data.get("messages", [])
    dated = [_date(m) for m in msgs if _date(m)]
    dated.sort()

    media_counts = {}
    poll_count = 0
    forwarded = 0
    for m in msgs:
        k = _media_kind(m)
        if k:
            media_counts[k] = media_counts.get(k, 0) + 1
        if m.get("poll"):
            poll_count += 1
        if m.get("forwarded_from"):
            forwarded += 1

    print(f"name:     {data.get('name')}")
    print(f"type:     {data.get('type')}")
    print(f"id:       {data.get('id')}")
    print(f"messages: {len(msgs)}")
    if dated:
        print(f"range:    {dated[0][:10]} → {dated[-1][:10]}")
    if forwarded:
        print(f"forwarded: {forwarded}")
    if poll_count:
        print(f"polls:    {poll_count}")
    if media_counts:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(media_counts.items()))
        print(f"media:    {parts}")


def cmd_search(args):
    data = _load(args.path)
    msgs = data.get("messages", [])

    flags = 0 if args.case_sensitive else re.IGNORECASE
    if args.regex:
        pattern = re.compile(args.query, flags)
    else:
        pattern = re.compile(re.escape(args.query), flags)

    results = []
    for m in msgs:
        if not _in_date_range(m, args.since, args.until):
            continue
        if args.media and _media_kind(m) != args.media:
            continue
        if args.min_reactions and _total_reactions(m) < args.min_reactions:
            continue

        haystacks = [_msg_text(m)]
        if m.get("forwarded_from"):
            haystacks.append(str(m["forwarded_from"]))
        poll = m.get("poll")
        if poll:
            haystacks.append(poll.get("question", ""))

        match = None
        for h in haystacks:
            match = pattern.search(h)
            if match:
                break
        if not match:
            continue

        results.append((m, _msg_text(m), match))

    if args.limit:
        results = results[: args.limit]

    if args.json:
        for m, text, _ in results:
            print(json.dumps({
                "id": m.get("id"),
                "date": _date(m),
                "from": m.get("from"),
                "text": text,
                "media": _media_kind(m),
            }, ensure_ascii=False))
        return

    if not results:
        print("no matches", file=sys.stderr)
        return

    for m, text, match in results:
        snip = _snippet(text or "", match, args.width)
        meta = _date(m)[:16].replace("T", " ")
        tags = []
        k = _media_kind(m)
        if k:
            tags.append(k)
        if m.get("forwarded_from"):
            tags.append(f"fwd:{m['forwarded_from']}")
        tagstr = ("  [" + " | ".join(tags) + "]") if tags else ""
        print(f"#{m.get('id')}  {meta}{tagstr}")
        if snip:
            print(f"    {snip}")
    print(f"\n{len(results)} match(es)", file=sys.stderr)


def _parse_ids(specs):
    ids = []
    for spec in specs:
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part and not part.startswith("-"):
                a, b = part.split("-", 1)
                ids.extend(range(int(a), int(b) + 1))
            else:
                ids.append(int(part))
    return ids


def _print_message(m, full=True):
    meta = _date(m).replace("T", " ")
    header = f"#{m.get('id')}  {meta}  {m.get('from') or m.get('actor') or ''}"
    print(header)

    if m.get("type") == "service":
        print(f"  [service: {m.get('action')}] {m.get('title') or ''}")

    if m.get("forwarded_from"):
        print(f"  [forwarded from: {m['forwarded_from']}]")
    if m.get("reply_to_message_id"):
        print(f"  [reply to: #{m['reply_to_message_id']}]")

    k = _media_kind(m)
    if k and k != "poll":
        extra = []
        if m.get("file_name"):
            extra.append(m["file_name"])
        if m.get("duration_seconds"):
            extra.append(f"{m['duration_seconds']}s")
        if m.get("width") and m.get("height"):
            extra.append(f"{m['width']}x{m['height']}")
        print(f"  [{k}{' ' + ', '.join(extra) if extra else ''}]")

    text = _msg_text(m)
    if text:
        for line in text.split("\n"):
            print(f"  {line}")

    poll = m.get("poll")
    if poll:
        print(f"  [poll] {poll.get('question')}  ({poll.get('total_voters')} voters)")
        for a in poll.get("answers", []):
            print(f"    - {a.get('text')}: {a.get('voters')}")

    print()


def cmd_show(args):
    data = _load(args.path)
    msgs = data.get("messages", [])
    by_id = {m.get("id"): m for m in msgs}
    order = [m.get("id") for m in msgs]

    ids = _parse_ids(args.ids)

    want = []
    seen = set()
    for i in ids:
        if args.context and i in by_id:
            pos = order.index(i)
            lo = max(0, pos - args.context)
            hi = min(len(order), pos + args.context + 1)
            for j in order[lo:hi]:
                if j not in seen:
                    seen.add(j)
                    want.append(j)
        else:
            if i not in seen:
                seen.add(i)
                want.append(i)

    if args.json:
        out = [by_id[i] for i in want if i in by_id]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    for i in want:
        m = by_id.get(i)
        if not m:
            print(f"#{i}  (not found)\n")
            continue
        _print_message(m)


def register(subparsers):
    p = subparsers.add_parser(
        "tgscope",
        help="search and read Telegram chat/channel JSON exports",
    )
    sp = p.add_subparsers(dest="action", required=True)

    info = sp.add_parser("info", help="overview of an export")
    info.add_argument("path", help="export dir or result.json")
    info.set_defaults(func=cmd_info)

    search = sp.add_parser("search", help="search messages")
    search.add_argument("path", help="export dir or result.json")
    search.add_argument("query", help="text or regex to search for")
    search.add_argument("--regex", action="store_true", help="treat query as regex")
    search.add_argument(
        "--case-sensitive", action="store_true", help="case-sensitive match"
    )
    search.add_argument("--since", help="only messages on/after YYYY-MM-DD")
    search.add_argument("--until", help="only messages on/before YYYY-MM-DD")
    search.add_argument("--media", help="only this media kind (photo, video_file, ...)")
    search.add_argument(
        "--min-reactions", type=int, default=0, help="min total reactions"
    )
    search.add_argument("--limit", type=int, default=0, help="max results")
    search.add_argument(
        "--width", type=int, default=200, help="snippet width in chars"
    )
    search.add_argument("--json", action="store_true", help="output JSONL")
    search.set_defaults(func=cmd_search)

    show = sp.add_parser("show", help="print full messages by id")
    show.add_argument("path", help="export dir or result.json")
    show.add_argument(
        "ids", nargs="+", help="message ids: '12', '12,15', or range '10-20'"
    )
    show.add_argument(
        "--context",
        type=int,
        default=0,
        help="also show N neighbor messages before/after each id",
    )
    show.add_argument("--json", action="store_true", help="output raw JSON")
    show.set_defaults(func=cmd_show)


def run(args):
    args.func(args)
