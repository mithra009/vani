"""Export renders: every format on a 5 s fixture with a cut, music and two voice clips.
Checks the G4 contract: duration within one frame of duration_t and voice where the editor shows it."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from editor_service import export, timeline

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
FRAME = 1 / 25


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("exp")
    ff("-f", "lavfi", "-i", "testsrc=duration=6:size=640x360:rate=25", "-f", "lavfi", "-i", "sine=f=300:d=6",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "src.mp4"))
    for name, f in (("v1.wav", 800), ("v2.wav", 1200)):
        ff("-f", "lavfi", "-i", f"sine=f={f}:d=0.8", "-ar", "48000", str(d / name))
    ff("-f", "lavfi", "-i", "sine=f=100:d=4", str(d / "music.mp3"))
    return d


def snapshot():
    doc = timeline.default_doc(6.0)
    doc, _ = timeline.apply(doc, {"type": "video.split", "clip_id": "vc0", "at_src": 2.0, "new_id": "b"}, source_s=6.0)
    doc, _ = timeline.apply(doc, {"type": "video.split", "clip_id": "b", "at_src": 3.0, "new_id": "c"}, source_s=6.0)
    doc, _ = timeline.apply(doc, {"type": "video.delete", "clip_id": "b"}, source_s=6.0)     # 5 s long
    doc, _ = timeline.apply(doc, {"type": "music.add", "clip": {"id": "m", "media_id": "mu", "t": 1.0, "fade_in": 0.5}},
                            source_s=6.0, media={"mu": 4.0})
    chunks = [
        {"id": "a", "idx": 0, "text": "First line.", "anchor_src_s": 0.5, "anchor_len_s": 0.8, "audio_duration_s": 0.8},
        {"id": "x", "idx": 1, "text": "Cut away.", "anchor_src_s": 2.5, "anchor_len_s": 0.4, "audio_duration_s": 0.8},
        {"id": "z", "idx": 2, "text": "After the cut.", "anchor_src_s": 4.0, "anchor_len_s": 0.8, "audio_duration_s": 0.8},
    ]
    return {"doc": doc, "chunks": chunks}


def make_plan(media, fmt, height=480, audio_mix="full"):
    return export.plan_from_snapshot(
        snapshot(), fmt=fmt, height=height, audio_mix=audio_mix, source=str(media / "src.mp4"),
        source_has_audio=True, source_height=360,
        chunk_paths={"a": str(media / "v1.wav"), "x": str(media / "v1.wav"), "z": str(media / "v2.wav")},
        media_paths={"mu": str(media / "music.mp3")},
    )


def test_plan_places_voice_like_the_editor_and_warns_about_the_cut(media):
    plan, warnings, caps = make_plan(media, "mp4")
    assert plan.duration == 5.0
    assert [(round(v.t, 3), v.length) for v in plan.voices] == [(0.5, 0.8), (3.0, 0.8)]   # z: 4.0 - 1 s cut
    assert {"chunk_id": "x", "flags": ["video_cut"]} in warnings
    assert [c["text"] for c in caps] == ["First line.", "After the cut."]


@pytest.mark.parametrize("fmt", ["mp4", "webm", "mov", "mp3", "wav"])
def test_render_every_format(media, tmp_path, fmt):
    plan, _, _ = make_plan(media, fmt, height=None if fmt in ("mp3", "wav") else 480)
    out = tmp_path / f"out.{fmt}"
    ff(*export.build_args(plan, str(out))[1:])    # build_args starts with -y
    info = probe(out)
    assert abs(float(info["format"]["duration"]) - 5.0) <= FRAME + 0.03, info["format"]["duration"]
    kinds = {s["codec_type"] for s in info["streams"]}
    assert kinds == ({"audio"} if fmt in ("mp3", "wav") else {"audio", "video"})
    if "video" in kinds:
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        assert v["height"] == 360                  # 480 requested, never upscaled


def test_voice_lands_at_its_timeline_position(media, tmp_path):
    plan, _, _ = make_plan(media, "wav", height=None, audio_mix="voice")
    out = tmp_path / "voice.wav"
    ff(*export.build_args(plan, str(out))[1:])
    x, sr = sf.read(out)
    x = np.abs(x).mean(axis=1) if x.ndim > 1 else np.abs(x)
    win = int(sr * 0.01)
    env = x[: len(x) // win * win].reshape(-1, win).mean(axis=1)
    on = np.flatnonzero(env > env.max() * 0.2)
    starts = [on[0]] + [b for a, b in zip(on, on[1:]) if b - a > 5]
    assert [round(s * 0.01, 2) for s in starts] == pytest.approx([0.5, 3.0], abs=0.03)


def test_burned_captions_render(media, tmp_path):
    plan, _, caps = make_plan(media, "mp4")
    caps[0]["text"] = r"ನಾನು ಇವತ್ತು ಸ್ಟಾಕ್ {\b1}"           # Indic conjuncts + an attempted override tag
    (tmp_path / "captions.ass").write_text(export.captions_ass(caps, export.output_height(plan)), encoding="utf-8")
    plan.burn_captions = "captions.ass"
    subprocess.run(["ffmpeg", *export.build_args(plan, "out.mp4")], cwd=tmp_path, check=True, capture_output=True)
    assert abs(float(probe(tmp_path / "out.mp4")["format"]["duration"]) - 5.0) <= FRAME + 0.03


def test_no_voice_no_original_still_renders_silence(media, tmp_path):
    plan, _, _ = make_plan(media, "mp3", height=None, audio_mix="voice")
    plan.voices = []
    ff(*export.build_args(plan, str(tmp_path / "s.mp3"))[1:])
    assert abs(float(probe(tmp_path / "s.mp3")["format"]["duration"]) - 5.0) < 0.06


def test_captions_files():
    caps = [{"start": 61.5, "end": 62.25, "text": "Hi"}]
    assert export.captions_file(caps, "srt") == "1\n00:01:01,500 --> 00:01:02,250\nHi\n"
    assert export.captions_file(caps, "vtt").startswith("WEBVTT\n\n00:01:01.500 --> 00:01:02.250\nHi")


def test_captions_ass_is_sized_to_the_output_and_strips_override_tags():
    ass = export.captions_ass([{"start": 1.5, "end": 3.25, "text": r"Hi {\b1}there"}], 720)
    assert "PlayResY: 720" in ass and "PlayResX: 1280" in ass
    assert "Style: Default,Noto Sans,40," in ass
    assert r"Dialogue: 0,0:00:01.50,0:00:03.25,Default,,0,0,0,,Hi (\b1)there" in ass
