import os
import sys
import urllib.request

from .models import GEMINI_TEXT


MODEL = GEMINI_TEXT["flash"]


def resolve_vertex_url(vertex_uri):
    try:
        req = urllib.request.Request(vertex_uri, method="HEAD")
        req.add_header("User-Agent", "gski-websearch/1.0")
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        resp = opener.open(req, timeout=5)
        return resp.url
    except Exception:
        return vertex_uri


def extract_search_info(interaction):
    queries = []
    sources = []
    seen = set()

    for step in getattr(interaction, "steps", []) or []:
        stype = getattr(step, "type", None)
        if stype == "google_search_call":
            args = getattr(step, "arguments", None)
            q = getattr(args, "queries", None) if args else None
            if not q and isinstance(args, dict):
                q = args.get("queries")
            if q:
                queries.extend(q)
        elif stype == "model_output":
            for block in getattr(step, "content", []) or []:
                for ann in getattr(block, "annotations", []) or []:
                    if getattr(ann, "type", None) == "url_citation":
                        url = getattr(ann, "url", None) or getattr(ann, "uri", None)
                        title = getattr(ann, "title", "")
                        if url and url not in seen:
                            seen.add(url)
                            resolved_url = (
                                resolve_vertex_url(url)
                                if "vertexaisearch.cloud.google.com" in url
                                else url
                            )
                            sources.append({"url": resolved_url, "title": title})

    return queries, sources


def format_output(interaction):
    text = getattr(interaction, "output_text", "") or ""
    queries, sources = extract_search_info(interaction)

    if sources:
        text += "\n\n---\nSources:\n"
        for i, src in enumerate(sources[:8]):
            title_suffix = f" ({src['title']})" if src.get("title") else ""
            text += f"[{i + 1}] {src['url']}{title_suffix}\n"

    if queries:
        text += f"\nSearch queries: {', '.join(queries)}\n"

    return text


def register(subparsers):
    p = subparsers.add_parser(
        "websearch", help="search the web via Gemini with Google Search grounding"
    )
    p.add_argument("query", help="search query or question")
    p.add_argument(
        "--sources",
        action="store_true",
        help="also print resolved source URLs and the search queries used",
    )
    p.set_defaults(func=run)


def run(args):
    if not os.environ.get("GEMINI_API_KEY"):
        print("error: GEMINI_API_KEY env var required", file=sys.stderr)
        sys.exit(1)

    from google import genai

    client = genai.Client()

    interaction = client.interactions.create(
        model=MODEL,
        input=args.query,
        tools=[{"type": "google_search"}],
    )

    if args.sources:
        print(format_output(interaction))
    else:
        print(interaction.output_text or "")
