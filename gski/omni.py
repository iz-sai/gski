import sys
from pathlib import Path

from gski.deepresearch_lib.format import fmt_age, truncate
from gski.models import GEMINI_OMNI as MODELS
from gski.omni_lib.api import (
    build_generation_config,
    build_input,
    build_response_format,
    download_video,
    extract_video,
    interactions_create,
    make_client,
    new_interaction_id,
    poll,
)
from gski.omni_lib.state import (
    all_jobs,
    load_job,
    new_job,
    record_interaction,
    remove_job,
    save_job,
    video_path_for,
)

ASPECT_RATIOS = ["16:9", "9:16"]
TASKS = ["text_to_video", "image_to_video", "reference_to_video", "edit"]


def _finish(job, client, interaction, output):
    data, uri, mime = extract_video(interaction)
    internal = video_path_for(job["job_id"])
    download_video(client, data, uri, internal)
    job["video_path"] = str(internal)
    job["state"] = "completed"
    save_job(job)

    if output:
        out = Path(output)
        out.write_bytes(internal.read_bytes())
        print(out)
    else:
        print(internal)


def _resume_hint(job_id):
    print(f"\nresume with: gski omni wait {job_id}", file=sys.stderr)


def cmd_generate(args):
    client = make_client()
    model = MODELS["flash"]

    user_input = build_input(args.prompt, args.image, args.video, client)
    kwargs = {
        "model": model,
        "input": user_input,
        "background": True,
        "store": True,
        "response_format": build_response_format(args.aspect_ratio),
    }
    gen_config = build_generation_config(args.task)
    if gen_config:
        kwargs["generation_config"] = gen_config

    interaction = interactions_create(client, **kwargs)
    iid = new_interaction_id(interaction)

    job = new_job(prompt=args.prompt, model=model)
    record_interaction(job, iid, "generate", args.prompt)
    save_job(job)

    print(f"job:         {job['job_id']}")
    print(f"interaction: {iid}")
    print(f"state:       {job['state']}")

    if not args.wait:
        _resume_hint(job["job_id"])
        return

    result = poll(client, iid)
    _finish(job, client, result, args.output)


def cmd_edit(args):
    job = load_job(args.id)
    client = make_client()

    interaction = interactions_create(
        client,
        model=job["model"],
        input=args.prompt,
        previous_interaction_id=job["current_interaction_id"],
        background=True,
        store=True,
        response_format=build_response_format(args.aspect_ratio),
    )
    iid = new_interaction_id(interaction)
    record_interaction(job, iid, "edit", args.prompt)
    job["state"] = "running"
    save_job(job)

    print(f"job:         {job['job_id']}")
    print(f"interaction: {iid}")
    print(f"state:       running")

    if not args.wait:
        _resume_hint(job["job_id"])
        return

    result = poll(client, iid)
    _finish(job, client, result, args.output)


def cmd_list(args):
    jobs = all_jobs()
    if not args.all:
        jobs = [j for j in jobs if j.get("state") not in ("completed", "failed")]

    if not jobs:
        print("(no jobs)")
        return

    print(f"{'JOB':<10}  {'STATE':<10}  {'AGE':<6}  PROMPT")
    for j in jobs:
        print(
            f"{j['job_id']:<10}  "
            f"{j.get('state', '?'):<10}  "
            f"{fmt_age(j.get('updated_at', '')):<6}  "
            f"{truncate(j.get('prompt', ''), 60)}"
        )


def cmd_status(args):
    job = load_job(args.id)
    client = make_client()
    iid = job["current_interaction_id"]
    interaction = client.interactions.get(iid)
    remote_status = getattr(interaction, "status", "unknown")

    print(f"job:         {job['job_id']}")
    print(f"state:       {job['state']}")
    print(f"remote:      {remote_status}")
    print(f"interaction: {iid}")
    print(f"created:     {job['created_at']}  ({fmt_age(job['created_at'])} ago)")
    print(f"prompt:      {job['prompt']}")
    if job.get("video_path"):
        print(f"video:       {job['video_path']}")


def cmd_wait(args):
    job = load_job(args.id)

    if job["state"] == "completed" and job.get("video_path"):
        print(job["video_path"])
        return

    client = make_client()
    result = poll(client, job["current_interaction_id"])
    _finish(job, client, result, args.output)


def cmd_show(args):
    job = load_job(args.id)
    vp = job.get("video_path")
    if not vp or not Path(vp).exists():
        print("error: no saved video for this job", file=sys.stderr)
        sys.exit(1)
    print(vp)


def cmd_rm(args):
    job = load_job(args.id)
    remove_job(job, keep_video=args.keep_video)
    print(f"removed job {job['job_id']}")


def register(subparsers):
    p = subparsers.add_parser(
        "omni",
        help="Gemini Omni Flash — stateful video generation and editing",
    )
    sp = p.add_subparsers(dest="action", required=True)

    gen = sp.add_parser("generate", help="generate a video from text/image/video inputs")
    gen.add_argument("prompt", help="text prompt")
    gen.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="FILE",
        help="reference/first-frame image (repeatable)",
    )
    gen.add_argument("--video", metavar="FILE", help="source video to edit/transform")
    gen.add_argument(
        "--aspect-ratio",
        choices=ASPECT_RATIOS,
        metavar="RATIO",
        help="output aspect ratio (16:9 default, 9:16 portrait)",
    )
    gen.add_argument(
        "--task",
        choices=TASKS,
        help="explicit task hint (inferred from prompt if unset)",
    )
    gen.add_argument("--output", "-o", help="also write the video to this path")
    gen.add_argument(
        "--wait", action="store_true", help="block until the video is ready"
    )
    gen.set_defaults(func=cmd_generate)

    edit = sp.add_parser("edit", help="edit a job's video with a follow-up prompt")
    edit.add_argument("id", help="job id (prefix ok)")
    edit.add_argument("prompt", help="edit instruction")
    edit.add_argument(
        "--aspect-ratio", choices=ASPECT_RATIOS, metavar="RATIO", help="output aspect ratio"
    )
    edit.add_argument("--output", "-o", help="also write the video to this path")
    edit.add_argument("--wait", action="store_true", help="block until the video is ready")
    edit.set_defaults(func=cmd_edit)

    lst = sp.add_parser("list", help="list tracked jobs")
    lst.add_argument("--all", "-a", action="store_true", help="include completed jobs")
    lst.set_defaults(func=cmd_list)

    stat = sp.add_parser("status", help="check status of a job (no polling)")
    stat.add_argument("id", help="job id (prefix ok)")
    stat.set_defaults(func=cmd_status)

    wait = sp.add_parser("wait", help="resume polling until the video is ready")
    wait.add_argument("id", help="job id (prefix ok)")
    wait.add_argument("--output", "-o", help="also write the video to this path")
    wait.set_defaults(func=cmd_wait)

    show = sp.add_parser("show", help="print saved video path")
    show.add_argument("id", help="job id (prefix ok)")
    show.set_defaults(func=cmd_show)

    rm = sp.add_parser("rm", help="remove a job from local tracking")
    rm.add_argument("id", help="job id (prefix ok)")
    rm.add_argument("--keep-video", action="store_true", help="keep saved video file")
    rm.set_defaults(func=cmd_rm)
