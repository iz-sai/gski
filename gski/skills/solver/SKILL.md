---
name: gski solver
description: Creative problem-solving toolkit — TRIZ, SCAMPER, Lateral Thinking, Six Hats, Morphological Analysis
---

## How it works

`gski solver` provides structured creative problem-solving frameworks as CLI tools. It handles the mechanical parts that LLMs do poorly: true randomness, data lookups, and enforced structure. You (the LLM) provide the creative thinking.

The tool does NOT call any LLM. It outputs data, random selections, and structured prompts that you then apply to the user's problem.

## Modes

### 1. TRIZ — Systematic invention

TRIZ (Theory of Inventive Problem Solving) resolves contradictions: when improving one thing worsens another. The contradiction matrix maps 39 engineering parameters to 40 inventive principles.

**When to use:** The user has a problem where improving X makes Y worse. A trade-off, a dilemma, a "we can't have both" situation.

**Workflow:**
1. Help the user identify which two parameters are in contradiction
2. Run `gski solver triz --list params` to show available parameters
3. Run `gski solver triz --improve <ID> --worsen <ID>` to look up principles
4. Apply each suggested principle to the user's specific problem
5. If no matrix entry exists, use `gski solver triz --random -n 3` for inspiration

```bash
# List all 39 parameters
gski solver triz --list params

# List all 40 principles
gski solver triz --list principles

# Look up contradiction: improve Speed while Strength worsens
gski solver triz --improve 9 --worsen 14

# Random principles for inspiration
gski solver triz --random -n 3
```

### 2. SCAMPER — Quick idea generation

Seven operators that force you to transform an existing idea/product/process. Each operator comes with sub-questions.

**When to use:** The user wants to improve, innovate, or rethink something that already exists. Good for product ideas, process improvement, feature brainstorming.

**Workflow:**
1. Run `gski solver scamper -n 2` (or more) to get random operators
2. For each operator, systematically answer every sub-question about the user's problem
3. Don't skip operators that seem irrelevant — forced application produces the best ideas

```bash
# Pick 2 random operators
gski solver scamper -n 2

# All 7 operators
gski solver scamper -n 7
```

### 3. Lateral Thinking — Random provocation

De Bono's random word technique. Introduces truly random, unrelated concepts to break out of logical thinking patterns. The LLM cannot effectively self-provoke — it needs external randomness.

**When to use:** The user is stuck, needs fresh perspectives, or the problem requires genuinely novel thinking. Best for "we've tried everything" situations.

**Workflow:**
1. Run `gski solver lateral -n 3` to get random words and a movement technique
2. Pick one word, list its properties/associations (5+)
3. Use the given movement technique to bridge from each association to the problem
4. Do NOT filter ideas — capture everything, evaluate later
5. If stuck, run again for fresh words

**Critical rule:** Never reject a word as "too random." The harder the connection, the more creative the result.

```bash
# 3 random provocation words + technique
gski solver lateral -n 3

# More words for bigger session
gski solver lateral -n 6
```

### 4. Six Thinking Hats — Structured perspective shifts

Forces systematic thinking from 6 different angles. Prevents the LLM's default of giving a "balanced" answer that actually covers nothing deeply.

**When to use:** Decision-making, evaluating proposals, comprehensive analysis. When the user needs to think through something from all angles instead of jumping to conclusions.

**Workflow:**
1. Choose a sequence based on the goal, or use random
2. Run `gski solver hats --sequence <name>` or `gski solver hats --random`
3. Go through each hat IN ORDER — spend real effort on each one
4. Under each hat, answer ALL the forcing questions for the user's problem
5. Do NOT mix hats — stay in one perspective at a time

**Sequences:**
- `problem_solving` — Blue → White → Green → Red → Yellow → Black → Blue
- `evaluation` — Blue → Red → White → Yellow → Black → Green → Blue
- `quick_decision` — Blue → White → Red → Black → Blue
- `idea_generation` — Blue → White → Green → Red → Blue
- `risk_assessment` — Blue → White → Yellow → Black → Red → Green → Blue

```bash
# Named sequence
gski solver hats --sequence problem_solving

# Random sequence (blue bookends)
gski solver hats --random
```

### 5. Morphological Analysis — Combinatorial exploration

Break a problem into independent dimensions (axes), then randomly combine values across axes to find non-obvious solutions.

**When to use:** Design problems with multiple independent variables. "What combination of X, Y, Z should we use?" Product design, architecture decisions, strategy.

**Workflow:**
1. Help the user identify 3-6 independent axes/dimensions of their problem
2. Run `gski solver morph "axis1" "axis2" "axis3" -n 5`
3. For each axis, brainstorm 3-5 concrete options
4. The tool suggests random axis pairings — explore those combinations first
5. Evaluate which combinations are surprising and worth pursuing

```bash
# 3 axes, 4 random pairings
gski solver morph "material" "form factor" "power source" -n 4

# More axes
gski solver morph "auth method" "data store" "API style" "deployment" "pricing" -n 5
```

## Choosing a mode

| Situation | Best mode |
|-----------|-----------|
| Trade-off / contradiction / "can't have both" | `triz` |
| Improve existing product/process/idea | `scamper` |
| Completely stuck, need fresh thinking | `lateral` |
| Need thorough analysis from all angles | `hats` |
| Design problem with multiple variables | `morph` |
| Don't know what to use | Start with `lateral`, then `scamper` |

## Combining modes

Modes work well together in sequence:
1. `hats --sequence problem_solving` to understand the problem fully
2. `triz` if a contradiction is identified (or `scamper` if not)
3. `lateral` to break out if stuck during step 2
4. `morph` to systematically explore the solution space
5. `hats --sequence evaluation` to evaluate the best ideas

## Key principles

- **True randomness matters.** Run the CLI for random selections — don't pick them yourself. Your pattern matching will subconsciously choose "safe" options.
- **Don't skip what seems irrelevant.** Forced application of an "irrelevant" operator or word often produces the best ideas.
- **Separate generation from evaluation.** Generate ideas freely first (green hat), evaluate later (black/yellow hat).
- **One perspective at a time.** Don't give a "balanced" answer. Go deep on each angle separately.
