---
name: gski voiceover
description: Text-to-speech voiceovers via ElevenLabs or Gemini — AI narration with voice and delivery control
---

## How it works

`gski voiceover` (alias `gski tts`) turns text into an audio file with one of two providers, chosen by `--provider`. Prints the output path.

| | `elevenlabs` (default) | `gemini` |
|---|---|---|
| Auth | `ELEVENLABS_API_KEY` (or `ELEVEN_LABS_API_KEY`) | `GEMINI_API_KEY` |
| Delivery control | numeric knobs (`--stability`, `--style`, `--similarity`, `--speed`) + `[tags]` in text | one short `--direction` string + `<tags>` in text |
| Tag syntax | square brackets: `[laughs]` | angle brackets: `<laugh>` |
| Voices | your ElevenLabs library, by name or id | 30 prebuilt names, or custom `voice_...` id |
| Output | mp3 (default), pcm, wav... via `--format` | mp3 (default) or wav |
| Language | per model | detected automatically |

**Reference docs (read for prompting details):** `docs/elevenlabs_tts.md`, `docs/gemini-tts.md`.

## Commands

```bash
# ElevenLabs (default provider)
gski voiceover "Welcome back."
gski voiceover "[laughs] Dude — it just built the whole thing itself." --voice "Blain - Conversational Ad Voice"
gski voiceover "Please hold." --stability 0.5 --style 0.2 -o out/hold.mp3
gski voiceover --list-voices

# Gemini
gski voiceover "Welcome back." --provider gemini
gski voiceover "Wait... <short pause> did you hear that? <gasp>" --provider gemini --voice Puck --direction "whispered urgently"
gski voiceover "Final cut." --provider gemini -o out/final.wav
gski voiceover --provider gemini --list-voices
```

## Common options

| Flag | Notes |
|------|-------|
| `text` | positional; tag syntax depends on provider |
| `--provider` | `elevenlabs` (default) or `gemini` |
| `--voice` | provider-specific, see below |
| `--model` | provider-specific, see below |
| `--format` | provider-specific, see below; with gemini the `-o` extension (`.mp3`/`.wav`) also works |
| `--output-dir` | default `./output`, auto-named `voiceover_<ts>.<ext>` |
| `-o, --output` | explicit path, overrides auto-naming |
| `--list-voices` | print voices of the chosen provider and exit |

Flags of the other provider (e.g. `--stability` with `--provider gemini`) are an error.

## ElevenLabs

- Models: `v4` (default, expressive, only one that reads audio tags), `multilingual` (stable), `flash` (fast/cheap). Always stay on `v4` unless explicitly asked for bulk (`flash`) or stable corporate reads (`multilingual`). Earlier models (e.g. `v3`) are prohibited.
- Default voice: Blain.

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--stability` | 0-1 | `0.1` | lower = more expressive |
| `--style` | 0-1 | `1.0` | style exaggeration |
| `--similarity` | 0-1 | `1.0` | adherence to source voice |
| `--speed` | 0.7-1.2 | `1.2` | hard max 1.2 |
| `--no-speaker-boost` | flag | on | disable similarity boost |
| `--format` | codec_rate_bitrate | `mp3_44100_128` | e.g. `mp3_44100_192`, `pcm_44100`, `wav_44100` |

Voices (name searches your library; the voice must already be in it):

| Name | Voice ID | Notes |
|------|----------|-------|
| Blain (default) | `jHprmvvyQreWpRuutdmV` | Conversational Ad Voice |
| Goblin Dub | `ExH3OkS7Pkt4jwaUHbVK` | Custom IVC voice, isolated Goblin dub |

Tags (v4 only): `[excited]` `[confident]` `[sarcastic]` `[curious]` `[whispers]` `[nervously]` `[reassuring]` · `[laughs]` `[laughs harder]` `[sighs]` `[exhales]` `[clears throat]` `[gulps]`. Use `...` for pauses, CAPS for emphasis. A voice can only do what its training supports.

Notes: char cap per request v4/multilingual 10,000, flash 40,000. `mp3_44100_192` needs Creator tier+, PCM/WAV 44.1kHz needs Pro+. Cost ≈ 1 credit/char (flash 0.5), ~$0.18 per 1,000 chars.

## Gemini

- Model: `flash` (only choice, default).
- Default voice: Iapetus.
- Text is read verbatim as a transcript: never put stage directions in it, put them in `--direction`.
- `--direction TEXT`: short delivery for the whole text, e.g. `"whispered urgently"`, `"warm and enthusiastic"`, `"speaking slowly"`, `"sarcastic"`, `"out of breath"`. Omit it first; add only if the plain read needs a tweak. Keep it short — long persona descriptions make the voice drift. Don't try to change age, gender or accent there; pick another voice.
- `--format`: `mp3` (default, via ffmpeg) or `wav` (lossless, 24 kHz mono).

Inline tags (angle brackets, momentary sounds, keep them in English even for non-English text):
`<laugh>` `<chuckle>` `<giggle>` `<cackle>` `<snicker>` `<snort>` · `<sigh>` `<gasp>` `<cough>` `<throat-clearing>` `<sneeze>` `<yawn>` `<tsk>` `<phew>` `<exhales>` · `<breath>` `<heavy breath>` `<pant>` · `<cry>` `<sob>` `<whimper>` · `<groan>` `<moan>` `<grunt>` `<growl>` `<hiss>` · `<scream>` `<shout>` `<shriek>` `<cheer>` `<argh>` · `<whispers>` · `<short pause>` `<long pause>`.
Pacing: `...` and `--` for hesitation, CAPS for emphasis. Avoid sound-effect tags (applause, thuds).

Voices (`--voice`, case-insensitive; `voice_...` / `voicekey_...` ids from voice design/replication also accepted):

| Voice | Style | Voice | Style | Voice | Style |
|---|---|---|---|---|---|
| Zephyr | Bright | Puck | Upbeat | Charon | Informative |
| Kore | Firm | Fenrir | Excitable | Leda | Youthful |
| Orus | Firm | Aoede | Breezy | Callirrhoe | Easy-going |
| Autonoe | Bright | Enceladus | Breathy | **Iapetus** | Clear |
| Umbriel | Easy-going | Algieba | Smooth | Despina | Smooth |
| Erinome | Clear | Algenib | Gravelly | Rasalgethi | Informative |
| Laomedeia | Upbeat | Achernar | Soft | Alnilam | Firm |
| Schedar | Even | Gacrux | Mature | Pulcherrima | Forward |
| Achird | Friendly | Zubenelgenubi | Casual | Vindemiatrix | Gentle |
| Sadachbia | Lively | Sadaltager | Knowledgeable | Sulafat | Warm |

Single speaker only. Output is generated as WAV; mp3 needs `ffmpeg`.
