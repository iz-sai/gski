---
name: gski websearch
description: Search the web using Google Search via Gemini grounding — current events, facts, documentation
---

## How it works

`gski websearch` sends your text to Gemini with Google Search enabled. Gemini rewrites it into its own search queries, reads the results, and answers with sources. The text you send is both the question and the seed for those searches: whatever names and terms you put in it end up in the searches.

Vertex AI Search redirect URLs are resolved to the actual source URLs. Default model is `gemini-3.8-flash`.

## Usage

```bash
gski websearch "question or topic"
gski websearch "question" --sources   # also print source URLs and the searches Gemini ran
```

Default output is the answer text only. With `--sources`: a `Sources:` list (URL + site) and the `Search queries:` Gemini actually ran. If those queries are not what you meant, rephrase.

## Writing the query

It is a question to an LLM, not a keyword box. Plain sentences work. You can also state what you want back (comparison, numbers, dates, primary sources) and how wide to look.

Pick the situation:

- **You know the entity and want facts about it** (docs, release, API, bug, price): name it exactly.
- **You don't know the answer and are looking for it** (best, newest, alternatives, what exists): describe the problem and what "good" means. Do not name candidates from your own memory; they bias results toward themselves and your memory may be outdated.
- **You have a candidate but want to know if it is still the best**: name it once and say explicitly to look beyond it, e.g. "is X still the best choice for Y, and what is newer or better?".
- **Comparing specific things**: name them all, and ask for the criteria you care about.

Add a time anchor ("latest", a year) only when recency matters.
