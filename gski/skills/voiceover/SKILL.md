---
name: gski voiceover
description: Text-to-speech voiceovers via ElevenLabs — expressive AI narration with voice/emotion control
---

## How it works

`gski voiceover` (alias `gski tts`) sends text to the ElevenLabs Text-to-Speech API and saves an audio file. Use the `v3` model for expressive delivery with inline audio tags like `[laughs]`.

Requires `ELEVENLABS_API_KEY` (also accepts `ELEVEN_LABS_API_KEY`).

**Prompting/tuning reference:** `docs/elevenlabs_tts.md` — read it for models, voice settings, audio tags, punctuation, and pricing.

## Commands

```bash
# Basic (default voice Blain, v3, high-energy defaults)
gski voiceover "The first move is what sets everything in motion."

# Pick a voice by name (searches your library) or by voice_id
gski voiceover "Welcome back." --voice "Blain - Conversational Ad Voice"
gski voiceover "Welcome back." --voice jHprmvvyQreWpRuutdmV

# Expressive social/reaction style with v3 audio tags
gski voiceover "[laughs] Dude — it just built the whole thing itself. I'm just watching it go."

# Cheaper/faster model, explicit output file
gski voiceover "Bulk line 42." --model flash -o out/line42.mp3

# Calmer read: raise stability, drop style
gski voiceover "Please hold while I connect you." --stability 0.5 --style 0.2

# List available voices (id, name, category)
gski voiceover --list-voices
```

## Options

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `text` | positional | — | text to speak; v3 audio tags allowed |
| `--voice` | name or voice_id | Blain | name searches your library (exact then substring) |
| `--model` | `v3`, `multilingual`, `flash` | `v3` | v3 = expressive+tags; multilingual = stable; flash = fast/cheap |
| `--stability` | 0-1 | `0.1` | lower = more expressive/varied |
| `--style` | 0-1 | `1.0` | style exaggeration |
| `--similarity` | 0-1 | `1.0` | adherence to source voice |
| `--speed` | 0.7-1.2 | `1.2` | native speech speed (hard max 1.2) |
| `--no-speaker-boost` | flag | on | disable similarity boost |
| `--format` | codec_rate_bitrate | `mp3_44100_128` | e.g. `mp3_44100_192`, `pcm_44100`, `wav_44100` |
| `--output-dir` | path | `./output` | auto-named `voiceover_<ts>.<ext>` |
| `-o, --output` | FILE | — | explicit path, overrides auto-naming |
| `--list-voices` | flag | — | print voices and exit |

## Notes

- Only `v3` interprets audio tags (`[laughs]`, `[whispers]`, ...). multilingual/flash ignore them.
- Per-request char caps: v3 5,000 · multilingual 10,000 · flash 40,000.
- `mp3_44100_192` needs Creator tier+; PCM/WAV 44.1kHz needs Pro tier+.
- The voice must already be in your library; add shared-library voices via the web app first.
- Cost ≈ 1 credit/char (flash 0.5), ~$0.18 per 1,000 chars. See docs for tier limits.
