# Video Voice-Over Studio

*Working title.*

Upload a video, pick a language and a voice, and get the video back dubbed into Hindi, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati, Punjabi, English or Hinglish. Each dubbed line starts exactly where the original line started, and the output is exactly as long as the input.


> **Status: planning.** No code yet. The architecture, requirements, challenges and roadmap are in [PLAN.md](PLAN.md).

---

## How it works

```
video ─► extract audio ─► Prisma v2.5 Batch STT ─► you review the transcript
      ─► Evon v3.3 translates each line to fit its time slot
      ─► Timbre v2.5 (or a clone of the speaker's voice) speaks each line
      ─► fit each line to its slot (speed + pitch-preserving stretch)
      ─► place lines at their original timestamps ─► mix with the original audio ─► MP4 + subtitles
```

1. **Transcribe:** Gnani Prisma v2.5 Batch STT returns timestamped segments, and can tell multiple speakers apart.
2. **Review:** fix any recognition mistakes before anything is spent on synthesis.
3. **Translate to fit:** Evon v3.3 translates each line within a character budget worked out from the line's duration and the chosen voice's speaking rate.
4. **Speak:** pick one of Gnani's 42 Timbre v2.5 voices, or clone the original speaker from a 5–30 s sample (with consent).
5. **Fit:** each line is sped up or slowed within natural limits (Timbre `speed` 0.85–1.15 plus ffmpeg `atempo`). Lines that still don't fit get a shorter translation or are flagged for you.
6. **Assemble:** every line is placed at its *own* start time, so errors can't add up over a long video. The original audio is lowered under the dub, the video stream is copied untouched, and the audio is cut to the exact video length.

## Gnani models used

| Model | Used for |
|---|---|
| Prisma v2.5 (Batch STT) | Timestamped transcription, speaker diarization |
| Timbre v2.5 (TTS) | Persona voices in 10 languages + Hinglish |
| Voice-clone TTS | Dubbing in the original speaker's voice |
| Evon v3.3 | Length-aware translation |

## What it does not do
- **Lip sync:** mouths won't match the new language.
- **Languages outside Gnani's ten plus Hinglish.**
- **Real-time dubbing:** it's an upload-and-wait tool.
- **Music separation:** the original track is lowered (or muted) under the dub, not removed.

## Requirements
- Python 3.12, Node 20+, ffmpeg 6+ on PATH
- A Gnani API key in `.env` as `GNANI_API_KEY`
- Access to the Evon v3.3 weights and somewhere to run them (likely a 24 GB GPU, see PLAN.md §4.3)

## Setup and running
*Added when the first stage is built.*

## Responsible use
Only dub videos you own or have permission to use. Only clone a voice with its owner's consent. Cloned output is labelled as AI-generated. Demo material uses self-recorded, synthetic content only.
