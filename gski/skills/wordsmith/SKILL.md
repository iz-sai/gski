---
name: wordsmith
description: Write and edit prose for humans - technical explanation, announcements, essays, direct-response copy - and strip AI tells from existing drafts
---

No CLI, no API key. Prompt-only skill: you do the work, this sets the rules.

## When to use

Any prose a human reads: README intro, docs, incident note, release announcement, post, email, landing page, essay. Not commit messages or code comments.

Scale the effort to the stakes:

- **Short** (a paragraph, a chat message, one section): skip to Part 2, run Part 3 in your head.
- **Real** (published, sold, or read by strangers): all three parts, in order.
- **Existing draft**: go straight to Part 3.

For anything over a few paragraphs, also read `structure.md` in this directory.

---

# The tells

Structure and syntax give AI prose away, not vocabulary. Fix in that order.

## Structural

| Tell | Before | After |
|---|---|---|
| Throat-clearing | "In today's fast-paced development landscape, CI speed matters." | "Builds took 45 minutes. Nobody could say why." |
| Announced plan | "This post will cover three approaches to caching." | "There are three ways to cache this. Two are wrong." |
| Binary contrast | "This isn't just a bridge. It's a complete communication layer." | "It bridges Telegram to four MCP servers over one chat." |
| Mic-drop fragment | "The result? Total clarity. That's it." | "You watch one number instead of nine." |
| Triad padding | "Fast, scalable, and reliable infrastructure." | "40k requests a second, no downtime since March." |
| Symmetric bullets | Every section given exactly three bullets | Give each section the number of points it has |
| Wrap-up paragraph | "In conclusion, caching is a powerful tool that..." | Delete it. Stop at the last real point. |
| Rhetorical hook | "Ever wondered why your builds are slow?" | "Your builds are slow because the cache key has a timestamp in it." |

## Syntactic

| Tell | Before | After |
|---|---|---|
| Participial tail | "It retries uploads, ensuring seamless data integrity." | "It retries uploads. Nothing is lost when the network drops." |
| Second participial tail | "...allowing you to focus on what matters." | Cut entirely. It says nothing. |
| Zombie noun | "Implementation of the migration was performed by the team." | "The team migrated it." |
| Passive evasion | "Mistakes were made in the rollout." | "I rolled it out without testing the migration." |
| Hedge stack | "It could be argued this may potentially reduce some costs." | "This cuts about 30% of the spend." |
| Colon reveal | "The best part: it runs offline." | "It runs offline." |
| Not-only-but-also | "Not only does it transcribe, but it also summarizes." | "It transcribes, then summarizes." |
| From-X-to-Y sweep | "From solo developers to large enterprises..." | Name one reader. Delete the sweep. |
| Vague adjective | "Dramatically improves developer productivity." | "Builds dropped from 45 minutes to 3." |
| Monotone cadence | "The system validates the schema. The system transforms the records. The system logs failures." | "It validates the schema first. Then it transforms the records, writes them out, and logs whatever broke." |

## Tonal

| Tell | Before | After |
|---|---|---|
| Sycophantic opener | "Great question! Let's dive in." | Start with the answer. |
| Forced enthusiasm | "This is a fun little tool to play with!" | "It does one thing and it does it in 200ms." |
| Fake conversational | "Here's the thing: caching is hard." | "Caching is hard because invalidation has no general solution." |
| Vague attribution | "Studies show that developers prefer..." | "In the 2024 SO survey, 61% said..." or cut the claim. |
| Anthropomorphism | "The parser wants well-formed input." | "The parser rejects anything that isn't well-formed." |
| Over-gloss | "It caches results. This means results are stored for reuse." | "It caches results." |

## Vocabulary, punctuation, formatting

**Symptom words**, not the disease: delve, tapestry, realm, beacon, testament, multifaceted, seamless, elevate, unlock, unleash, empower, holistic, synergy, game-changer, revolutionize, groundbreaking, paramount, indispensable. Swapping one for a synonym fixes nothing. `robust`, `leverage`, `landscape` are fine when technically literal, wrong when decorative.

**Punctuation.** Em-dashes read as machine-written past two or three per page. Ration them.

**Formatting.** Bold-for-emphasis on more than a couple of phrases per screen is a tell. So is a bullet list where a sentence would do.

---

# Part 1 - Brief

Do not draft from a one-line request. Get these, inferring from context, files, and the repo first, then asking for the rest in **one** round.

Always:

| Slot | Test it passes |
|---|---|
| Reader | One named person, not "teams" or "developers" |
| The one thing | What they should know or do, in a single sentence |
| Proof | Numbers, names, cases you actually have |

Persuasion adds:

| Slot | Test it passes |
|---|---|
| Pain | Stated in their words, as a concrete daily friction |
| Mechanism | Why this works when what they tried didn't |
| Cost of the ask | Time, money, and risk to say yes |

Worked example, for a release note:

> Reader: someone who records voice memos on Linux and never gets around to typing them up.
> One thing: one keybind turns a memo into text in the clipboard.
> Proof: 3 seconds round trip on a 30-second memo. Falls back to Gemini when OpenAI is down.
> Pain: memos sit in a folder for a week untranscribed.
> Mechanism: no app to open. The hotkey records, uploads, and pastes back.
> Cost: pip install, plus an API key you already have.

Two standing rules:

- If proof is empty, write the sentence without a number. Never invent one.
- For persuasion, name the awareness stage first: unaware, problem-aware, solution-aware, product-aware, most aware. Unaware needs a story. Most aware needs a price.

**If the user won't answer**, say what you assumed in one line and draft anyway. Do not stall, and do not paper over the gap with adjectives.

**If there is genuinely nothing to say**, say that instead of writing. A release note for a change nobody feels is noise.

---

# Part 2 - Draft

Pick one register, then one shape inside it. Do not blend shapes.

## Explanatory

Docs, README, incident notes, release announcements, technical posts.

> What it is in one line. Why you would want it. How it works. Where it breaks. How to start.

Lead with the conclusion. State the limitation before the reader finds it themselves. No sales register anywhere in this mode: a README that pitches loses trust on the first paragraph.

> **vault-mcp** exposes your Obsidian vault to an agent over MCP: read, write, search.
>
> It runs stdio by default, or SSE when you need it over the network. Search is plain substring matching over file contents, so it is fast and it will miss synonyms. Point it at a vault directory and add it to your MCP config.

## Essay and opinion

Argument, retrospective, position.

Write the spine first: the argument as a numbered list of one-line claims, each asserting something. If that list does not hold together, prose will not save it. `structure.md` has the six shapes and the rest of the method.

## Persuasion

Something is being sold or asked for.

| Job | Shape |
|---|---|
| Landing page, cold email, ad | PAS: Problem, Agitate the compounding cost, Solution |
| Case study, social proof, re-engagement | BAB: Before, After, Bridge (the mechanism) |
| Long sales page, launch | PASTOR: Problem, Amplify, Story, Transformation, Offer, Response |
| Pricing and packaging | Value equation: raise dream outcome and perceived likelihood, cut time delay and effort. Then bonuses, risk reversal, name |

One reader, one idea, one ask.

## Titles and headlines

The highest-leverage line in the piece, and the one most often written on autopilot. Write ten, pick one. Write it last.

| Pattern | Example |
|---|---|
| The specific number | "Cutting CI from 45 minutes to 3" |
| The flat claim | "Most retry logic makes outages worse" |
| The named thing plus what it does | "vault-mcp: an agent that reads your Obsidian vault" |
| The anomaly | "The cache key had a timestamp in it" |

Not allowed: questions, colons used for drama ("Caching: what nobody tells you"), gerund-plus-abstraction ("Unlocking the power of caching"), and numbered listicles unless the piece really is a list.

## Lists or prose

A bullet list is right when items are parallel and order does not matter. It is cowardice when one thing causes another, because bullets let you skip saying how they connect. Never bullet a causal chain, a sequence with dependencies, or an argument. Those are paragraphs.

## Voice

If samples exist, name three observable features before writing: average sentence length, first person or not, jargon level. Then match them.

> Sample reads: 8-14 words a sentence, first person singular, assumes the reader knows what a socket is.

Do not describe a voice in adjectives ("punchy, friendly"). Copy its shape. Without samples, default to plain declarative.

Write the first pass ugly and specific: arguments and proof, no polish. Polish is Part 3.

---

# Part 3 - Red pen

Two passes. Never three, because a third flattens it.

**Cut.** Delete every tell above. Drop filler (very, actually, basically, really, simply). Delete any sentence that restates the one before it. Remove setup until the piece starts mid-action.

**Sharpen.** Passive to active. Adjective to number or noun. Nominalization to verb. Break anything over 25 words. Change openers so no two consecutive sentences start the same way. Vary sentence length by reading it aloud in your head, never by hitting a quota.

Worked pass, 78 words to 47:

> **Before.** "In today's rapidly evolving development landscape, managing multiple MCP servers can be a significant challenge. Our new bridge tool provides a robust and seamless solution, allowing you to connect your agents to Telegram effortlessly. It's not just a bridge, it's a complete communication layer. Furthermore, it handles reconnection automatically, ensuring your messages are never lost. Whether you're a solo developer or part of a large team, agent-bridge streamlines your entire workflow."
>
> **After.** "Running four MCP servers means four terminals, and no way to reach any of them from your phone. agent-bridge puts one Telegram chat in front of all four. It reconnects on its own and queues messages while it's down, so a dropped connection costs you nothing."
>
> Removed: throat-clearing opener, two participial tails, a binary contrast, a Furthermore, a from-X-to-Y sweep, and `robust`, `seamless`, `streamlines`, `effortlessly`.

Ship when all six are true:

- [ ] Opens mid-action, no setup
- [ ] Every claim carries a number, a name, or an explicit "unknown"
- [ ] No sentence you would not say out loud
- [ ] Sentence lengths vary, with no punchy-fragment tic
- [ ] At least 15% shorter than the draft
- [ ] One ask, stated once

Output the rewritten text first. Then at most three lines of audit: what you cut, and what still needs a real number. Never return audit alone.

## Editing someone else's writing

Preserve their voice, fix their structure. Their word choices and rhythms stay unless they are one of the tells. Do not smooth a distinctive sentence into a correct one. When you cut a claim for lack of proof, say so rather than silently softening it.

---

# Failure modes

- Drafting before the brief is filled. Generic copy, every time.
- Inventing proof to fill an empty slot.
- Sales register in explanatory writing.
- Editing to flatness. Slight roughness reads human, perfect symmetry does not.
- Blending shapes. A PAS page with a PASTOR middle loses both.
- Bulleting an argument to avoid making it.
- Trading one cliché for a fresher one and calling it a fix.
