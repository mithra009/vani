import numpy as np
import pytest

from backend.app import emotion as emo
from backend.app import fit, media


# ---------- fit: segment normalisation & slots ----------

def seg(a, b, text="word " * 5, speaker=1):
    return {"start_s": a, "end_s": b, "text": text.strip(), "speaker": speaker}


def test_short_segments_merge_into_close_neighbour():
    out = fit.normalise([seg(0, 0.8, "haan"), seg(0.9, 3.0, "main aa raha hoon")])
    assert len(out) == 1 and out[0]["end_s"] == 3.0 and out[0]["text"] == "haan main aa raha hoon"


def test_segments_with_a_real_gap_stay_separate():
    assert len(fit.normalise([seg(0, 0.8, "haan"), seg(1.5, 3.0)])) == 2


def test_different_speakers_never_merge():
    assert len(fit.normalise([seg(0, 0.8, "haan", 1), seg(0.9, 3.0, "theek", 2)])) == 2


def test_long_segment_splits_at_widest_pause():
    s = seg(0, 20, " ".join(f"w{i}" for i in range(40)))
    out = fit.normalise([s], pauses=[(5.0, 5.2), (9.0, 10.0), (15, 15.1)])
    assert len(out) == 2
    assert out[0]["end_s"] == 9.0 and out[1]["start_s"] == 10.0
    assert len(out[0]["text"].split()) + len(out[1]["text"].split()) == 40


def test_slots_end_before_next_line_and_at_video_end():
    out = fit.slots([seg(0, 2), seg(3, 5)], duration=8)
    assert out[0]["slot_end_s"] == pytest.approx(3 - fit.SLOT_GUARD_S)
    assert out[1]["slot_end_s"] == 8


# ---------- fit: prediction, speed, decisions ----------

def test_tags_count_toward_predicted_time():
    plain = fit.predict_seconds("a" * 26, cps=13)
    tagged = fit.predict_seconds("<laugh> " + "a" * 26 + " <pauses>", cps=13)
    assert plain == pytest.approx(2.0)
    assert tagged == pytest.approx(2.0 + fit.TAG_SECONDS["laugh"] + 0.75)


def test_speed_is_clamped_and_fitting_beats_emotion():
    assert fit.choose_speed(3.0, 2.0) == 1.15                      # needs 1.5×, capped
    assert fit.choose_speed(1.0, 2.0) == 1.0                       # fits easily
    assert fit.choose_speed(1.0, 2.0, emotion_speed=0.9) == 0.9    # sad: slower allowed
    assert fit.choose_speed(2.1, 2.0, emotion_speed=0.9) == 1.05   # but fitting wins


@pytest.mark.parametrize("actual,slot,gap,speed,short,action", [
    (1.8, 2.0, 0.5, 1.0, False, "place"),
    (2.2, 2.0, 0.5, 1.0, False, "stretch"),
    (2.6, 2.0, 0.5, 1.0, False, "retry_short"),
    (2.25, 2.0, 0.5, 1.15, True, "stretch"),   # 1.125× × 1.15 still under the 1.3× cap
    (2.28, 2.0, 0.5, 1.15, True, "borrow"),    # 1.14× would exceed the cap → borrow gap
    (3.5, 2.0, 0.0, 1.0, True, "flag"),
])
def test_fit_decisions(actual, slot, gap, speed, short, action):
    assert fit.decide(actual, slot, gap, speed, short).action == action


def test_total_pace_never_exceeds_cap():
    d = fit.decide(4.0, 2.0, 0.3, 1.15, True)
    assert d.action == "flag" and d.stretch * 1.15 <= 1.30 + 1e-6


# ---------- media: silence trim, placement ----------

def test_trim_silence_removes_padding():
    sr = 48000
    tone = 0.3 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr).astype(np.float32)
    x = np.concatenate([np.zeros(sr // 2, np.float32), tone, np.zeros(sr // 2, np.float32)])
    y = media.trim_silence(x, sr)
    assert abs(len(y) / sr - 1.0) < 0.06


def test_placement_is_sample_exact_and_clipped_at_end():
    tl = np.zeros(1000, np.float32)
    media.place(tl, np.ones(100, np.float32), start_s=0.5, sr=1000)
    assert tl[499] == 0 and tl[500] == 1 and tl[599] == 1 and tl[600] == 0
    media.place(tl, np.ones(100, np.float32), start_s=0.95, sr=1000)
    assert len(tl) == 1000 and tl[-1] == 1


# ---------- emotion ----------

def test_fusion_rules():
    assert emo.fuse("angry", 2, "low") == ("neutral", 1)        # text says angry, voice is calm
    assert emo.fuse("sad", 2, "high") == ("neutral", 1)
    assert emo.fuse("neutral", 1, "high") == ("excited", 1)
    assert emo.fuse("angry", 2, "high") == ("angry", 3)
    assert emo.fuse("happy", 1, "whisper")[0] == "whisper"


def test_smoothing_keeps_strong_and_repeated_labels_only():
    out = emo.smooth([("neutral", 1), ("angry", 2), ("neutral", 1), ("sad", 2), ("sad", 2), ("excited", 3)])
    assert out[1] == ("angry", 1)          # lone mild label → speed/punctuation only
    assert out[3] == ("sad", 2) and out[4] == ("sad", 2)
    assert out[5] == ("excited", 3)


def test_mild_emotion_gets_no_tags():
    assert emo.controls("angry", 1)[0] == []
    assert emo.controls("angry", 2)[0] == ["shouting"]


def test_acoustic_features_on_synthetic_voice():
    sr = 16000
    t = np.arange(sr * 2) / sr
    x = (0.3 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)
    f = emo.features(x, sr)
    assert 140 < f["f0"] < 160
