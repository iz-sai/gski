---
name: decision-frameworks
description: Reasoning frameworks for discussions that converge on a decision - DD Double Diamond, SI Strong Inference, DL Dialectic, DC Double Crux, FP First Principles, PM Pre-mortem
---

No CLI. Prompt-only: pick a framework, run its steps out loud, keep the user in the loop.

Each framework answers a different question. Pick by the question, not by habit.
For idea generation techniques (TRIZ, SCAMPER, lateral, hats) use `solver`.

| Code | Framework | Question it answers |
|------|-----------|---------------------|
| DD | Double Diamond | What are the options at all? |
| SI | Strong Inference | Which of these options is right? |
| DL | Dialectic | Does this position survive its best counter? |
| DC | Double Crux | Why do we disagree? |
| FP | First Principles | Are we building on borrowed assumptions? |
| PM | Pre-mortem | How does this fail? |

## DD - Double Diamond

Two rounds of widen then narrow: first on the problem, then on the solution.

1. Discover: widen the problem. List what the problem might really be, who it hurts, what is unknown.
2. Define: narrow to one problem statement. State it in one sentence.
3. Develop: widen the solutions. 4-7 genuinely different options, no critique yet. Include one odd one.
4. Deliver: narrow. Cut by explicit criteria, keep 1-2.

Rule: never critique during a widen step, never add during a narrow step.

## SI - Strong Inference

Several hypotheses alive at once; kill them with discriminating facts.

1. List 2-5 competing hypotheses or options. Each must be concrete enough to be wrong.
2. For each pair, find what would separate them: a fact, a test, a number, a user preference.
3. Get that fact: reason it out, look it up, or ask the user one sharp question.
4. Drop what lost. Add a new hypothesis if the evidence suggests one.
5. Repeat until one stands or the remaining ones don't matter.

Rule: a question or search is worth doing only if its answer would kill something.

## DL - Dialectic

Build the position, build the strongest attack, merge.

1. Thesis: state the position as strongly and specifically as possible.
2. Antithesis: steelman the opposite. The version its smartest defender would argue, not a strawman.
3. Find what each side gets right that the other misses.
4. Synthesis: a position that keeps both truths. Often a condition: "X when A, Y when B".
5. The synthesis is the new thesis; repeat if it still feels unstable.

Rule: if the antithesis is easy to beat, it was not the strongest one.

## DC - Double Crux

For disagreement between agent and user, or between two options both defend.

1. State both positions plainly.
2. For each side: what single belief, if false, would flip it?
3. Find the crux: a belief both sides would update on.
4. Argue only the crux. Check it with facts or examples.
5. Resolve the crux and the original disagreement resolves with it.

Rule: no arguing conclusions, only cruxes.

## FP - First Principles

Strip the problem down to what is actually known, rebuild from there.

1. Write down the current belief or default approach.
2. List the assumptions under it.
3. For each: is it a fact, a constraint, or a convention? Mark it.
4. Drop conventions. Keep facts and real constraints.
5. Rebuild a solution from what remains. Compare with the default.

Rule: "everyone does it this way" is a convention, not a fact.

## PM - Pre-mortem

Assume the decision failed; explain why.

1. State the decision and a time horizon.
2. "It is later, and this failed badly." List concrete causes, as many as plausible.
3. Rank by likelihood times damage.
4. For the top ones: mitigate, add a tripwire to notice early, or change the decision.

Rule: failures must be specific to this decision, not generic risks.

## Combining

Typical chains:
- DD to get options -> SI to pick -> PM to stress the pick
- FP when every option looks the same -> DD
- DL when the answer is a trade-off, DC when the user and agent disagree

Switch frameworks when the current one stops producing progress. Say that you are switching.
