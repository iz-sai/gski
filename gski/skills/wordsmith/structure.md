# Structure

Load this for anything longer than a few paragraphs: essay, technical post, docs page, retrospective, announcement with an argument in it.

## 1. The spine comes before the prose

Write the argument as a numbered list of one-line claims. Every line must assert something. Labels are not claims.

Labels, useless:
> 1. Background 2. The problem 3. Our approach 4. Results

Claims, usable:
> 1. Builds took 45 minutes and nobody could say why.
> 2. The obvious fix, more runners, made it worse.
> 3. The cache key included the build timestamp.
> 4. Fixing the key cut builds to 3 minutes.

Read the list on its own. If it does not hold together as an argument, prose will not save it. Reorder, merge, or cut lines until it does. Each surviving line becomes a paragraph or a section.

## 2. Pick a shape

| Shape | Use when | Order |
|---|---|---|
| Exploratory | You genuinely do not know the answer yet | The question, the attempts, what you found, what is still open |
| Thesis | You know the answer and must defend it | Claim, evidence, strongest objection answered, consequence |
| Postmortem | Something broke or changed | What you expected, what happened, the surprise, what changed |
| Explainer | Teaching a mechanism | The problem, why obvious fixes fail, the mechanism, the limits |
| Case | One concrete story carries the point | Situation, complication, turn, what it means |
| Enumeration | Items are genuinely parallel and order does not matter | The list. If order matters, it is a spine in disguise, use another shape |

Do not mix. An exploratory opening on a thesis body reads as bait and switch: the reader can tell you knew the answer all along.

## 3. Openings

Open with the most specific true thing you have.

- The anomaly: "Builds took 45 minutes. Nobody could say why."
- The flat claim: "Most retry logic makes outages worse."
- The scene: "The sign on the shop door has said 'door sticks' for three years."
- The real question, but only if you cannot answer it yet.

Never open by defining the topic, announcing the plan ("This post will cover..."), or setting a general scene.

Then delete your first paragraph and read it again. It is usually warm-up, and the piece usually starts better without it.

## 4. Paragraphs

One idea per paragraph. The first sentence carries it, the rest support it.

**Skim test.** Read only the first sentence of each paragraph. That should reproduce your spine from step 1 and still make the argument. Where it does not, the idea is buried mid-paragraph. Move it up.

Vary length. A one-sentence paragraph hits hard, which is exactly why it works once or twice in a piece and never more.

## 5. Transitions

The best transition is the right order. If two paragraphs need a connective to feel joined, either the sequence is wrong or the second paragraph starts in the wrong place.

Instead of Furthermore, Moreover, Additionally: pick up a concrete word from the end of one paragraph and open the next with it.

> ...it turned out the cache key included the build timestamp.
>
> Timestamps in a cache key mean nothing is ever a hit.

## 6. Section headers

A header is a promise about what follows. Make it a specific claim or a plain noun, never clever and never a question.

The reader should be able to navigate by headers alone and come away with the argument. If your headers read "Background / Approach / Results", they are labels, and you have hidden the argument from anyone skimming. Use the spine lines instead, shortened.

Do not header every paragraph. Headers mark a change of subject, not a change of paragraph.

## 7. Endings

Stop at the last real point. Then cut one more paragraph.

Works: the consequence ("the cache key is now the only thing we review in CI"), an open question you are honest about, the smallest concrete next step.

Does not work: summarizing what you just said, restating the opening, telling the reader to be excited.

## 8. Length by form

Rough targets. Over them, you are padding; well under, you are skipping the argument.

| Form | Length |
|---|---|
| Chat or release announcement | 3 to 6 sentences |
| README intro | Two paragraphs before the install command |
| Docs section | One screen |
| Incident note | Half a page: what broke, blast radius, cause, fix, prevention |
| Technical post | 800 to 1500 words |
| Essay | As long as the argument, usually 1000 to 2500 |
| Landing page hero | A headline, two lines, one button |

## 9. Draft one sentence per line

Write the draft with every sentence on its own line. Repeated openers, monotone length, and orphaned claims all become visible immediately. Join the lines into paragraphs as the last step, after the red pen.

## 10. Two tests before shipping

**Stranger test.** Read it as someone with none of your context. Mark every point where they would ask "why?" or "says who?". Answer those or cut the claim.

**Cut test.** Remove 15%. What resists cutting is usually carrying the argument. What goes quietly was padding.
