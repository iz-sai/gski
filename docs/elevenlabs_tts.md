# ElevenLabs TTS — Prompting & Tuning Guide

Reference for `gski voiceover`. Covers models, voice settings, v3 audio tags, and delivery control.

## Models

| Key (`--model`) | API id | Quality | Latency | Cost | Best for |
|---|---|---|---|---|---|
| `v3` | `eleven_v3` | Highest, expressive, audio tags | Slow (non-realtime) | 1 credit/char | Ads, narration, character/dialogue |
| `multilingual` | `eleven_multilingual_v2` | High, stable, natural | Moderate | 1 credit/char | Long-form, professional VO |
| `flash` | `eleven_flash_v2_5` | Good, less nuanced | ~75ms | 0.5 credit/char | Real-time, bulk, cheapest |

Per-request char caps: v3 = 5,000 · multilingual = 10,000 · flash = 40,000. This is per generation, not a usage limit.

Use `v3` for expressive voiceovers. Only `v3` interprets audio tags like `[laughs]`.

## Voice settings (the numeric knobs)

There is **no system-prompt field**. Delivery is controlled only by (1) the text/tags and (2) these settings:

- **stability** (0–1): lower = broader emotional range and variation; higher = flatter/monotone. `0.5` default plays it safe and often sounds flat. Drop to `0.2–0.4` for life.
- **style** (0–1): exaggerates the speaker's flair/accent. Higher = more animated; `>0.8` risks artifacts.
- **similarity_boost** (0–1): how strictly it clones the reference voice. High = closer to original (also copies mic flaws); lower = smoother, slight drift.
- **speed** (0.7–1.2): native pace. `1.2` is the hard max.
- **use_speaker_boost**: extra similarity, slightly higher latency.

### High-energy defaults

`gski voiceover` defaults to `stability 0.1, style 1.0, similarity 1.0, speed 1.2` — fast, expressive delivery out of the box. For a calmer read, raise `--stability` (e.g. `0.5`) and drop `--style` (e.g. `0.2`).

## Writing text for v3

Write it as a **person actually talking**, not ad copy. Reactions, hesitations, and natural phrasing beat polished slogans.

### Audio tags (v3 only)

Bracketed cues control delivery. They only work if the voice's training supports that range (a calm voice won't `[shout]`).

- Emotion/delivery: `[excited]`, `[confident]`, `[sarcastic]`, `[curious]`, `[whispers]`, `[nervously]`, `[reassuring]`
- Non-verbal: `[laughs]`, `[laughs harder]`, `[sighs]`, `[exhales]`, `[clears throat]`, `[gulps]`
- Effects (experimental): `[applause]`, `[gunshot]`, `[strong French accent]`, `[sings]`

```
[laughs] Dude — Gemini just wrote the whole thing. Built the booth itself. I didn't touch anything, I'm just... watching it go.
```

### Punctuation

- **Ellipses (...)** — pauses and hesitation/weight
- **CAPITALIZATION** — emphasis
- **Standard punctuation** — natural rhythm; `?` and `!` shift intonation
- v3 does **not** support SSML `<break>` tags — use ellipses/tags instead. `<break time="1.5s" />` works on v2/multilingual only.

### Pronunciation

- v3: inline IPA in slashes, e.g. `"/ˌbaɪoʊˈkemɪstri/"` (~80–90% consistent).
- v2/flash: SSML `<phoneme alphabet="cmu-arpabet" ph="...">word</phoneme>` (flash_v2 only), or pronunciation dictionaries.

### Number normalization

On by default for multilingual v2 (reads `$1,000,000` as "one million dollars"). Flash disables it for latency and may misread numbers/dates — spell things out in the text or use multilingual for number-heavy copy.

## Pricing (credits)

Credits are a shared monthly pool. TTS = 1 credit/char (flash 0.5). Tiers: Free 10k · Starter $6/30k · Creator $22/121k · Pro $99/600k · Scale $299/1.8M · Business $990/6M. Effective rate ≈ $0.18 per 1,000 chars. Unused credits roll over up to 2 months (cap 3× monthly). Overage bills at the same rate.

## Workflow tips

- Iterate on wording first, then tune stability/style, then speed.
- Match tags to the voice's character; test a few generations (`seed` is best-effort only).
- Voice must be in your library. Add shared-library voices via the web app or the add-voice API before use.
