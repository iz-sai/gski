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
RESOLUTIONS = ["360p", "720p", "1080p", "4k"]
TASKS = ["text_to_video", "image_to_video", "reference_to_video", "edit", "extend"]


def _finish(job, client, interaction, output):
    status = getattr(interaction, "status", None)
    if status == "failed":
        job["state"] = "failed"
        save_job(job)
        err = getattr(interaction, "error", "unknown error")
        print(f"error: generation failed: {err}", file=sys.stderr)
        sys.exit(2)

    data, uri, _mime = extract_video(interaction)
    internal = video_path_for(job["job_id"])
    download_video(client, data, uri, internal)
    job["video_path"] = str(internal)
    job["state"] = "completed"
    save_job(job)

    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(internal.read_bytes())
        print(out)
    else:
        print(internal)


def _resume_hint(job_id):
    print(f"\nresume with: gski omni wait {job_id}", file=sys.stderr)


def _complete(job, client, interaction, output):
    status = getattr(interaction, "status", None)
    if status not in ("completed", "failed"):
        interaction = poll(client, job["current_interaction_id"])
    _finish(job, client, interaction, output)


def cmd_generate(args):
    client = make_client()
    model = MODELS["flash"]

    user_input = build_input(args.prompt, args.image, args.video, client)
    is_async = args.async_mode
    kwargs = {
        "model": model,
        "input": user_input,
        "background": is_async,
        "store": True,
        "stream": False,
        "response_format": build_response_format(
            args.aspect_ratio, args.resolution, args.duration
        ),
    }
    gen_config = build_generation_config(args.task)
    if gen_config:
        kwargs["generation_config"] = gen_config

    interaction = interactions_create(client, **kwargs)
    iid = new_interaction_id(interaction)

    job = new_job(
        prompt=args.prompt,
        model=model,
        aspect_ratio=args.aspect_ratio,
        resolution=args.resolution,
        duration=args.duration,
    )
    record_interaction(job, iid, "generate", args.prompt)
    save_job(job)

    print(f"job:         {job['job_id']}")
    print(f"interaction: {iid}")

    if is_async:
        print(f"state:       {job['state']}")
        _resume_hint(job["job_id"])
        return

    _complete(job, client, interaction, args.output)


def _follow_up(args, kind):
    job = load_job(args.id)
    client = make_client()
    is_async = args.async_mode
    user_input = build_input(
        args.prompt,
        getattr(args, "image", []),
        getattr(args, "video", []),
        client,
    )
    aspect_ratio = args.aspect_ratio or job.get("aspect_ratio") or "9:16"
    resolution = args.resolution or job.get("resolution") or "720p"
    duration = getattr(args, "duration", None) or job.get("duration")

    interaction = interactions_create(
        client,
        model=job["model"],
        input=user_input,
        previous_interaction_id=job["current_interaction_id"],
        background=is_async,
        store=True,
        stream=False,
        response_format=build_response_format(aspect_ratio, resolution, duration),
    )
    iid = new_interaction_id(interaction)
    record_interaction(job, iid, kind, args.prompt)
    job["aspect_ratio"] = aspect_ratio
    job["resolution"] = resolution
    if duration:
        job["duration"] = duration
    save_job(job)

    print(f"job:         {job['job_id']}")
    print(f"interaction: {iid}")

    if is_async:
        print(f"state:       running")
        _resume_hint(job["job_id"])
        return

    _complete(job, client, interaction, args.output)


def cmd_edit(args):
    _follow_up(args, "edit")


def cmd_extend(args):
    _follow_up(args, "extend")


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


def _add_media_options(parser, video_help):
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="FILE",
        help="image input in prompt-tag order (repeatable)",
    )
    parser.add_argument(
        "--video",
        action="append",
        default=[],
        metavar="FILE",
        help=f"{video_help} (repeatable)",
    )


def _add_output_options(parser, default_aspect=None, default_resolution=None):
    parser.add_argument(
        "--aspect-ratio",
        choices=ASPECT_RATIOS,
        default=default_aspect,
        metavar="RATIO",
        help="output aspect ratio" + (f" (default: {default_aspect})" if default_aspect else ""),
    )
    parser.add_argument(
        "--resolution",
        choices=RESOLUTIONS,
        default=default_resolution,
        help="output resolution"
        + (f" (default: {default_resolution})" if default_resolution else ""),
    )
    parser.add_argument(
        "--duration",
        help="clip duration (e.g. 4s, 5s, 10s; range 3s-10s)",
    )
    parser.add_argument("--output", "-o", help="also write the video to this path")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--wait",
        dest="async_mode",
        action="store_false",
        help="wait for the video (default)",
    )
    mode.add_argument(
        "--async",
        dest="async_mode",
        action="store_true",
        help="return a job id and generate in the background",
    )
    parser.set_defaults(async_mode=False)


def register(subparsers):
    p = subparsers.add_parser(
        "omni",
        help="Gemini Omni Flash — stateful video generation and editing",
    )
    sp = p.add_subparsers(dest="action", required=True)

    gen = sp.add_parser("generate", help="generate a video from text/image/video inputs")
    gen.add_argument("prompt", help="text prompt")
    _add_media_options(gen, "source/reference video")
    _add_output_options(gen, default_aspect="9:16", default_resolution="720p")
    gen.add_argument(
        "--task",
        choices=TASKS,
        help="fallback task hint; prefer describing the task in the prompt",
    )
    gen.set_defaults(func=cmd_generate)

    edit = sp.add_parser("edit", help="edit a job's video with a follow-up prompt")
    edit.add_argument("id", help="job id (prefix ok)")
    edit.add_argument("prompt", help="edit instruction")
    _add_media_options(edit, "reference video")
    _add_output_options(edit)
    edit.set_defaults(func=cmd_edit)

    extend = sp.add_parser("extend", help="extend a job's video at the end")
    extend.add_argument("id", help="job id (prefix ok)")
    extend.add_argument(
        "prompt",
        nargs="?",
        default="Extend this video.",
        help="continuation instruction (default: Extend this video.)",
    )
    _add_media_options(extend, "reference video")
    _add_output_options(extend)
    extend.set_defaults(func=cmd_extend)

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
