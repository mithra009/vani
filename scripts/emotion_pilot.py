"""Does Gnani Timbre apply audio tags in a given language? Voices one sentence plainly and with a few
tags, and saves each take so you can listen side by side. Costs one TTS call per take (4 by default).

    python scripts/emotion_pilot.py --lang kn-IN --voice <voice_id> --text "ನಮಸ್ಕಾರ, ಇವತ್ತು ನಾವು ಹೊಸ ವಿಷಯ ಕಲಿಯೋಣ."
    python scripts/emotion_pilot.py --lang en-IN --voice <voice_id> --text "Hello, today we learn something new." --tags shouting

Uses GNANI_API_KEY from .env. Takes go to pilot_out/emotion/<lang>/. If the tagged takes sound like the
plain one (and run about as long), Timbre ignores tags for that language.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import soundfile as sf  # noqa: E402

from backend.app.providers.gnani import GnaniSpeech  # noqa: E402
from editor_service.chunking import ALLOWED, NEUTRAL, tts_text  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", required=True, help="Timbre language code, e.g. kn-IN, te-IN, hi-IN, en-IN")
    ap.add_argument("--voice", required=True, help="persona voice_id (the one your project uses)")
    ap.add_argument("--text", required=True)
    ap.add_argument("--tags", nargs="+", default=["whispers", "shouting", "laugh"])
    a = ap.parse_args()
    bad = [t for t in a.tags if t not in ALLOWED]
    if bad:
        print(f"Unknown tags {bad}; choose from {sorted(ALLOWED)}", file=sys.stderr)
        return 2

    out = ROOT / "pilot_out" / "emotion" / a.lang
    out.mkdir(parents=True, exist_ok=True)
    speech = GnaniSpeech()
    for tag in [NEUTRAL, *a.tags]:
        text = tts_text(a.text, tag)
        wav = await speech.tts(text, a.voice, a.lang, 1.0)
        info = sf.info(io.BytesIO(wav))
        path = out / f"{tag}.wav"
        path.write_bytes(wav)
        print(f"{tag:<10} {info.frames / info.samplerate:5.2f}s  {path}   sent: {text}")
    print("\nListen to each file. Same sound and length as neutral.wav = the tag is ignored in this language.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
