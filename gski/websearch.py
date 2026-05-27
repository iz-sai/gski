import os
import sys
import urllib.request

from google import genai
from google.genai import types


MODELS = {
    "flash": "gemini-3.5-flash",
    "flash-lite": "gemini-3.1-flash-lite-preview",
}


def resolve_vertex_url(vertex_uri):
    try:
        req = urllib.request.Request(vertex_uri, method="HEAD")
        req.add_header("User-Agent", "gski-websearch/1.0")
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        resp = opener.open(req, timeout=5)
        return resp.url
    except Exception:
        return vertex_uri


def resolve_chunks(chunks):
    resolved = []
    for chunk in chunks:
        if not hasattr(chunk, "web") or not chunk.web:
            continue
        uri = chunk.web.uri or ""
        title = chunk.web.title or ""
        if "vertexaisearch.cloud.google.com" in uri:
            uri = resolve_vertex_url(uri)
        resolved.append({"uri": uri, "title": title})
    return resolved


def format_output(response):
    candidate = response.candidates[0]
    text = response.text or ""

    meta = getattr(candidate, "grounding_metadata", None)
    if not meta:
        return text

    chunks = getattr(meta, "grounding_chunks", None) or []
    resolved = resolve_chunks(chunks)[:5]

    if resolved:
        text += "\n\n---\nSources:\n"
        for i, src in enumerate(resolved):
            text += f"[{i + 1}] {src['uri']}\n"

    queries = getattr(meta, "web_search_queries", None) or []
    if queries:
        text += f"\nSearch queries: {', '.join(queries)}\n"

    return text


def register(subparsers):
    p = subparsers.add_parser(
        "websearch", help="search the web via Gemini with Google Search grounding"
    )
    p.add_argument("query", help="search query or question")
    p.add_argument(
        "--model",
        choices=list(MODELS.keys()),
        default="flash",
        help="model to use (default: flash)",
    )
    p.add_argument(
        "--raw",
        action="store_true",
        help="print raw response text without citation formatting",
    )
    p.set_defaults(func=run)


def run(args):
    if not os.environ.get("GEMINI_API_KEY"):
        print("error: GEMINI_API_KEY env var required", file=sys.stderr)
        sys.exit(1)

    client = genai.Client()
    model = MODELS[args.model]

    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        system_instruction="Always use Google Search to find the most current, up-to-date information before answering. Never rely on your training data alone.",
    )

    response = client.models.generate_content(
        model=model,
        contents=args.query,
        config=config,
    )

    if args.raw:
        print(response.text)
    else:
        print(format_output(response))
