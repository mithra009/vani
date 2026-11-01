"""Where does the voice change when Vani speeds a chunk up: Gnani's own speed, or ffmpeg's stretch?
Voices one sentence at 1.0 and 1.15 (Gnani's max), then builds the faster takes with ffmpeg, so each
step can be heard on its own. Costs 2 TTS calls.

    python scripts/speed_pilot.py --lang kn-IN --voice Lakshmi --text "ನಮಸ್ಕಾರ, ಇವತ್ತು ನಾವು ಹೊಸ ವಿಷಯ ಕಲಿಯೋಣ."

Takes go to pilot_out/speed/<lang>/:
  1_gnani_1.00.wav                 Gnani at normal speed (the reference)
  2_gnani_1.15.wav                 Gnani's own speed-up, at its max
  3_ffmpeg-atempo_1.15.wav         the 1.00 take sped to 1.15 by ffmpeg atempo: same speed as 2, other method
  4_vani-now_1.30.wav              what Vani does today for 1.30: Gnani 1.15, then atempo ×1.13
  5_rubberband_1.30.wav            the same 1.30 with ffmpeg rubberband (a higher-quality stretcher)

Compare 1↔2 (does Gnani's own speed change the voice?), 2↔3 (Gnani vs ffmpeg at the same speed),
and 4↔5 (whether a better stretcher would help). Uses ffmpeg on PATH (needs rubberband for take 5).

A ladder of more speeds (0.75× to 2×, each by atempo and rubberband, plus Vani's route above 1.15) goes
to pilot_out/speed/<lang>/ladder/. Re-run with --reuse to rebuild it from the takes you already have,
without calling Gnani again:

    python scripts/speed_pilot.py --lang kn-IN --reuse
    python scripts/speed_pilot.py --lang kn-IN --reuse --speeds 1.25,1.6,1.8
"""

from __future__ import annotations

import argparse
import asyncio
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import soundfile as sf  # noqa: E402

from backend.app.providers.gnani import GnaniSpeech  # noqa: E402

GNANI_MAX = 1.15
TARGET = 1.30


def seconds(path: Path) -> float:
    info = sf.info(str(path))
    return info.frames / info.samplerate


def stretch(src: Path, dst: Path, audio_filter: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter:a", audio_filter, str(dst)], check=True)


LADDER = "0.75,0.9,1.1,1.2,1.3,1.4,1.5,1.75,2.0"


def ladder(takes: dict, out: Path, speeds: list[float]) -> list[tuple[str, Path]]:
    """Every speed in `speeds`, by each method: ffmpeg atempo and rubberband straight from the 1.00 take,
    and (above Gnani's max) Vani's own route, Gnani 1.15 then ffmpeg for the rest."""
    d = out / "ladder"
    d.mkdir(exist_ok=True)
    made = []
    for sp in speeds:
        jobs = [(f"{sp:.2f}_atempo_from-1.00", takes["1_gnani_1.00"], f"atempo={sp:.4f}"),
                (f"{sp:.2f}_rubberband_from-1.00", takes["1_gnani_1.00"], f"rubberband=tempo={sp:.4f}:formant=preserved")]
        if sp > GNANI_MAX:
            rest = sp / GNANI_MAX
            jobs += [(f"{sp:.2f}_vani-now_gnani1.15+atempo", takes["2_gnani_1.15"], f"atempo={rest:.4f}"),
                     (f"{sp:.2f}_gnani1.15+rubberband", takes["2_gnani_1.15"], f"rubberband=tempo={rest:.4f}:formant=preserved")]
        for name, src, flt in jobs:
            try:
                stretch(src, d / f"{name}.wav", flt)
                made.append((name, d / f"{name}.wav"))
            except subprocess.CalledProcessError:
                print(f"(skipped {name}: this ffmpeg can't run {flt.split('=')[0]})")
    return made


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", required=True, help="Timbre language code, e.g. kn-IN, hi-IN, en-IN")
    ap.add_argument("--voice", help="a Timbre v3.0 voice, e.g. Lakshmi (not needed with --reuse)")
    ap.add_argument("--text", help="the sentence to voice (not needed with --reuse)")
    ap.add_argument("--reuse", action="store_true",
                    help="reuse the Gnani takes already in pilot_out/speed/<lang>/: no new Gnani calls")
    ap.add_argument("--speeds", default=LADDER, help=f"comma-separated speeds for the ladder (default {LADDER})")
    a = ap.parse_args()

    out = ROOT / "pilot_out" / "speed" / a.lang
    out.mkdir(parents=True, exist_ok=True)
    takes = {name: out / f"{name}.wav" for name in ("1_gnani_1.00", "2_gnani_1.15")}
    if a.reuse:
        missing = [str(p) for p in takes.values() if not p.exists()]
        if missing:
            print(f"--reuse needs the earlier Gnani takes; missing: {missing}", file=sys.stderr)
            return 2
    else:
        if not (a.voice and a.text):
            print("--voice and --text are required unless --reuse is given.", file=sys.stderr)
            return 2
        speech = GnaniSpeech()
        for name, speed in (("1_gnani_1.00", 1.0), ("2_gnani_1.15", GNANI_MAX)):
            wav = await speech.tts(a.text, a.voice, a.lang, speed)
            sf.info(io.BytesIO(wav))                               # fails loudly if Gnani didn't return WAV
            takes[name].write_bytes(wav)

    rest = TARGET / GNANI_MAX
    takes["3_ffmpeg-atempo_1.15"] = out / "3_ffmpeg-atempo_1.15.wav"
    stretch(takes["1_gnani_1.00"], takes["3_ffmpeg-atempo_1.15"], f"atempo={GNANI_MAX}")
    takes["4_vani-now_1.30"] = out / "4_vani-now_1.30.wav"
    stretch(takes["2_gnani_1.15"], takes["4_vani-now_1.30"], f"atempo={rest:.4f}")
    try:
        takes["5_rubberband_1.30"] = out / "5_rubberband_1.30.wav"
        stretch(takes["2_gnani_1.15"], takes["5_rubberband_1.30"], f"rubberband=tempo={rest:.4f}:formant=preserved")
    except subprocess.CalledProcessError:
        takes.pop("5_rubberband_1.30")
        print("(this ffmpeg has no rubberband filter; take 5 skipped)")

    rows = list(takes.items()) + ladder(takes, out, [float(x) for x in a.speeds.split(",") if x.strip()])
    base = seconds(takes["1_gnani_1.00"])
    for name, path in rows:
        s = seconds(path)
        print(f"{name:<36} {s:5.2f}s  ({base / s:4.2f}× vs 1.00)")
    print(f"\nFiles: {out}  (ladder in {out / 'ladder'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
