import sys
from pathlib import Path

from gski.deepresearch_lib.api import (
    AGENT_MODELS,
    build_input,
    extract_text,
    interactions_create,
    make_client,
    new_interaction_id,
    poll,
)
from gski.deepresearch_lib.format import fmt_age, print_job_header, print_job_row
from gski.deepresearch_lib.resolve import resolve_text
from gski.deepresearch_lib.state import (
    all_jobs,
    load_job,
    new_job,
    record_interaction,
    remove_job,
    report_path_for,
    save_job,
    save_report,
)


def _write_report(job, text, output):
    text = resolve_text(text)
    internal = save_report(job, text)
    save_job(job)
    if output:
        out = Path(output)
        out.write_text(text)
        print(f"report written to {out}")
    else:
        print(f"report saved to {internal}")


def _plan_next_hint(job_id):
    print(
        f"\nrefine:  gski deepresearch refine {job_id} 'your feedback'\n"
        f"approve: gski deepresearch approve {job_id}"
    )


# ---------------------------------------------------------------------------
# subcommands


def cmd_start(args):
    client = make_client()
    model = AGENT_MODELS["max" if args.max else "default"]

    user_input = build_input(args.query, args.files, client)
    kwargs = {"agent": model, "input": user_input, "background": True}
    if args.plan:
        kwargs["agent_config"] = {
            "type": "deep-research",
            "collaborative_planning": True,
        }

    interaction = interactions_create(client, **kwargs)
    iid = new_interaction_id(interaction)

    job = new_job(
        query=args.query,
        model=model,
        mode="plan" if args.plan else "direct",
        files=args.files,
    )
    record_interaction(job, iid, "plan" if args.plan else "execute", args.query)
    save_job(job)

    print(f"job:         {job['job_id']}")
    print(f"interaction: {iid}")
    print(f"state:       {job['state']}")

    if not args.wait:
        print(f"\nresume with: gski deepresearch wait {job['job_id']}")
        return

    result = poll(client, iid)
    text = extract_text(result)

    if args.plan:
        save_job(job)
        print("\n--- plan ---\n")
        print(text)
        _plan_next_hint(job["job_id"])
    else:
        job["state"] = "completed"
        save_job(job)
        _write_report(job, text, args.output)


def cmd_list(args):
    jobs = all_jobs()
    if not args.all:
        jobs = [j for j in jobs if j.get("state") not in ("completed", "failed")]

    if not jobs:
        print("(no jobs)")
        return

    print_job_header()
    for j in jobs:
        print_job_row(j)


def cmd_status(args):
    job = load_job(args.id)
    client = make_client()
    iid = job["current_interaction_id"]
    interaction = client.interactions.get(iid)
    remote_status = getattr(interaction, "status", "unknown")

    print(f"job:         {job['job_id']}")
    print(f"state:       {job['state']}")
    print(f"mode:        {job['mode']}")
    print(f"remote:      {remote_status}")
    print(f"interaction: {iid}")
    print(f"created:     {job['created_at']}  ({fmt_age(job['created_at'])} ago)")
    print(f"query:       {job['query']}")
    if job.get("report_path"):
        print(f"report:      {job['report_path']}")


def cmd_wait(args):
    job = load_job(args.id)

    if job["state"] == "completed":
        print(f"job already completed: {job.get('report_path')}")
        return

    client = make_client()
    result = poll(client, job["current_interaction_id"])
    text = extract_text(result)

    if job["mode"] == "plan" and job["state"] == "planning":
        save_job(job)
        print("\n--- plan ---\n")
        print(text)
        _plan_next_hint(job["job_id"])
        return

    job["state"] = "completed"
    save_job(job)
    _write_report(job, text, args.output)


def cmd_show(args):
    job = load_job(args.id)
    rp = job.get("report_path")
    if not rp or not Path(rp).exists():
        print("error: no saved report for this job", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(Path(rp).read_text())


def cmd_refine(args):
    job = load_job(args.id)
    if job["mode"] != "plan":
        print("error: job is not in planning mode", file=sys.stderr)
        sys.exit(1)
    if job["state"] != "planning":
        print(
            f"error: cannot refine job in state '{job['state']}'", file=sys.stderr
        )
        sys.exit(1)

    client = make_client()
    interaction = interactions_create(
        client,
        agent=job["model"],
        input=args.feedback,
        agent_config={"type": "deep-research", "collaborative_planning": True},
        previous_interaction_id=job["current_interaction_id"],
        background=True,
    )
    iid = new_interaction_id(interaction)
    record_interaction(job, iid, "refine", args.feedback)
    save_job(job)
    print(f"refining (interaction {iid})...")

    result = poll(client, iid)
    text = extract_text(result)
    save_job(job)
    print("\n--- plan ---\n")
    print(text)
    _plan_next_hint(job["job_id"])


def cmd_approve(args):
    job = load_job(args.id)
    if job["mode"] != "plan":
        print("error: job is not in planning mode", file=sys.stderr)
        sys.exit(1)
    if job["state"] != "planning":
        print(
            f"error: cannot approve job in state '{job['state']}'", file=sys.stderr
        )
        sys.exit(1)

    client = make_client()
    interaction = interactions_create(
        client,
        agent=job["model"],
        input=args.message,
        agent_config={"type": "deep-research", "collaborative_planning": False},
        previous_interaction_id=job["current_interaction_id"],
        background=True,
    )
    iid = new_interaction_id(interaction)
    record_interaction(job, iid, "execute", args.message)
    job["state"] = "running"
    save_job(job)
    print(f"job:         {job['job_id']}")
    print(f"interaction: {iid}")
    print("state:       running")

    if not args.wait:
        print(f"\nresume with: gski deepresearch wait {job['job_id']}")
        return

    result = poll(client, iid)
    text = extract_text(result)
    job["state"] = "completed"
    save_job(job)
    _write_report(job, text, args.output)


def cmd_rm(args):
    job = load_job(args.id)
    remove_job(job, keep_report=args.keep_report)
    print(f"removed job {job['job_id']}")


def cmd_resolve(args):
    src = Path(args.file)
    if not src.exists():
        print(f"error: file not found: {src}", file=sys.stderr)
        sys.exit(1)
    text = src.read_text()
    resolved = resolve_text(text)
    if args.output:
        dst = Path(args.output)
    else:
        dst = src.with_name(f"{src.stem}_resolved_links{src.suffix}")
    dst.write_text(resolved)
    print(f"wrote {dst}")


# ---------------------------------------------------------------------------


def register(subparsers):
    p = subparsers.add_parser(
        "deepresearch",
        help="Gemini Deep Research agent — async long-running research tasks",
    )
    sp = p.add_subparsers(dest="action", required=True)

    start = sp.add_parser("start", help="start a new research job")
    start.add_argument("query", help="research query")
    start.add_argument(
        "--file",
        "-f",
        action="append",
        default=[],
        dest="files",
        help="input file or URL (PDF/image), repeatable",
    )
    start.add_argument(
        "--max", action="store_true", help="use deep-research-max (more comprehensive)"
    )
    start.add_argument(
        "--plan",
        action="store_true",
        help="collaborative planning mode (returns plan first)",
    )
    start.add_argument(
        "--output",
        "-o",
        help="write final report to this path (also saved in state dir)",
    )
    start.add_argument(
        "--wait",
        action="store_true",
        help="block waiting for completion instead of returning immediately",
    )
    start.set_defaults(func=cmd_start)

    lst = sp.add_parser("list", help="list tracked jobs")
    lst.add_argument("--all", "-a", action="store_true", help="include completed jobs")
    lst.set_defaults(func=cmd_list)

    stat = sp.add_parser("status", help="check status of a job (no polling)")
    stat.add_argument("id", help="job id (prefix ok)")
    stat.set_defaults(func=cmd_status)

    wait = sp.add_parser("wait", help="resume polling until job completes")
    wait.add_argument("id", help="job id (prefix ok)")
    wait.add_argument("--output", "-o", help="write final report to this path")
    wait.set_defaults(func=cmd_wait)

    show = sp.add_parser("show", help="print saved report to stdout")
    show.add_argument("id", help="job id (prefix ok)")
    show.set_defaults(func=cmd_show)

    ref = sp.add_parser("refine", help="refine the plan (planning mode only)")
    ref.add_argument("id", help="job id (prefix ok)")
    ref.add_argument("feedback", help="refinement instructions")
    ref.set_defaults(func=cmd_refine)

    appr = sp.add_parser("approve", help="approve the plan and execute research")
    appr.add_argument("id", help="job id (prefix ok)")
    appr.add_argument(
        "--message",
        "-m",
        default="Plan looks good, proceed.",
        help="approval message sent to the agent",
    )
    appr.add_argument("--output", "-o", help="write final report to this path")
    appr.add_argument(
        "--wait", action="store_true", help="block waiting for completion"
    )
    appr.set_defaults(func=cmd_approve)

    rm = sp.add_parser("rm", help="remove a job from local tracking")
    rm.add_argument("id", help="job id (prefix ok)")
    rm.add_argument(
        "--keep-report", action="store_true", help="keep saved report file"
    )
    rm.set_defaults(func=cmd_rm)

    res = sp.add_parser(
        "resolve",
        help="resolve grounding-redirect links in a report file",
    )
    res.add_argument("file", help="path to report markdown file")
    res.add_argument(
        "--output", "-o", help="output path (default: <stem>_resolved_links.md)"
    )
    res.set_defaults(func=cmd_resolve)
