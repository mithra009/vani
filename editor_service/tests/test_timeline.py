"""Timeline model: apply/invert round trips, source↔timeline mapping, layout flags, rejections."""

import random

import pytest

from editor_service import timeline as tl
from editor_service.errors import InputInvalid

SRC = 30.0


def doc():
    return tl.default_doc(SRC)


def chunk(cid, idx, anchor, length=1.0, audio=1.0):
    return {"id": cid, "idx": idx, "anchor_src_s": anchor, "anchor_len_s": length, "audio_duration_s": audio}


def ap(d, op, **kw):
    return tl.apply(d, op, source_s=SRC, **kw)


def test_cut_out_the_middle_ripples_and_hides_voice():
    d, _ = ap(doc(), {"type": "video.split", "clip_id": "vc0", "at_src": 10.0, "new_id": "b"})
    d, _ = ap(d, {"type": "video.split", "clip_id": "b", "at_src": 15.0, "new_id": "c"})
    d, _ = ap(d, {"type": "video.delete", "clip_id": "b"})
    assert tl.duration_t(d) == 25.0
    assert tl.src_to_t(d, 5.0) == 5.0
    assert tl.src_to_t(d, 12.0) is None                    # cut (D2)
    assert tl.src_to_t(d, 20.0) == 15.0                    # rippled left
    placed, hidden = tl.layout(d, [chunk("a", 0, 5.0), chunk("x", 1, 12.0), chunk("z", 2, 20.0)])
    assert [p.chunk_id for p in placed] == ["a", "z"] and placed[1].t == 15.0
    assert hidden == [{"chunk_id": "x", "reason": "video_cut"}]


def test_reorder_moves_voice_with_its_video():
    d, _ = ap(doc(), {"type": "video.split", "clip_id": "vc0", "at_src": 10.0, "new_id": "b"})
    d, _ = ap(d, {"type": "video.move", "clip_id": "b", "index": 0})
    assert tl.src_to_t(d, 12.0) == 2.0 and tl.src_to_t(d, 3.0) == 23.0


def test_voice_offset_detach_and_flags():
    d, _ = ap(doc(), {"type": "voice.set", "chunk_id": "a", "fields": {"offset": 0.5}}, chunk_ids={"a", "b"})
    chunks = [chunk("a", 0, 1.0, audio=2.0), chunk("b", 1, 2.0, audio=1.0), chunk("c", 2, 29.5, audio=2.0)]
    placed, _ = tl.layout(d, chunks)
    by = {p.chunk_id: p for p in placed}
    assert by["a"].t == 1.5 and "overlap" in by["a"].flags and "overlap" in by["b"].flags   # D6
    assert "past_end" in by["c"].flags
    d, _ = ap(d, {"type": "voice.set", "chunk_id": "b", "fields": {"detached_t": 10.0}})
    by = {p.chunk_id: p for p in tl.layout(d, chunks)[0]}
    assert by["b"].t == 10.0 and not by["a"].flags


def test_muted_clips_dont_count_as_overlap():
    d, _ = ap(doc(), {"type": "voice.set", "chunk_id": "b", "fields": {"muted": True}})
    placed, _ = tl.layout(d, [chunk("a", 0, 1.0, audio=2.0), chunk("b", 1, 2.0)])
    assert all(not p.flags for p in placed)


def test_on_cut_flag_when_speech_runs_into_a_cut():
    d, _ = ap(doc(), {"type": "video.split", "clip_id": "vc0", "at_src": 10.0, "new_id": "b"})
    d, _ = ap(d, {"type": "video.delete", "clip_id": "b"})
    placed, _ = tl.layout(d, [chunk("a", 0, 9.5, length=2.0)])
    assert "on_cut" in placed[0].flags


def test_trim_shortens_voice():
    d, _ = ap(doc(), {"type": "voice.set", "chunk_id": "a", "fields": {"trim_in": 0.2, "trim_out": 0.3}})
    assert tl.layout(d, [chunk("a", 0, 1.0, audio=2.0)])[0][0].length == 1.5


def test_unplaced_and_unvoiced_chunks_are_reported():
    _, hidden = tl.layout(doc(), [{"id": "a", "idx": 0, "anchor_src_s": None, "audio_duration_s": 1},
                                  {"id": "b", "idx": 1, "anchor_src_s": 1.0, "audio_duration_s": None}])
    assert [h["reason"] for h in hidden] == ["unplaced", "no_audio"]


@pytest.mark.parametrize("op,needle", [
    ({"type": "video.delete", "clip_id": "vc0"}, "can't be empty"),
    ({"type": "video.trim", "clip_id": "vc0", "src_in": 5, "src_out": 4}, "after src_in"),
    ({"type": "video.trim", "clip_id": "vc0", "src_in": 0, "src_out": 99}, "between"),
    ({"type": "video.split", "clip_id": "vc0", "at_src": 0.05}, "at least"),
    ({"type": "video.split", "clip_id": "nope", "at_src": 5}, "No video clip"),
    ({"type": "voice.set", "chunk_id": "zzz", "fields": {"offset": 1}}, "no chunk"),
    ({"type": "voice.set", "chunk_id": "a", "fields": {"pitch": 1}}, "unknown field"),
    ({"type": "voice.set", "chunk_id": "a", "fields": {"gain_db": 40}}, "between"),
    ({"type": "track.set", "track": "captions", "fields": {"enabled": "yes"}}, "true/false"),
    ({"type": "track.set", "track": "video", "fields": {"gain_db": 1}}, "unknown track"),
    ({"type": "music.add", "clip": {"media_id": "m9"}}, "no uploaded audio"),
    ({"type": "music.add", "clip": {"media_id": "m1", "media_out": 99}}, "between"),
    ({"type": "explode"}, "Unknown op"),
    ("garbage", "Malformed"),
])
def test_bad_ops_are_rejected_loudly(op, needle):
    with pytest.raises(InputInvalid) as e:
        ap(doc(), op, chunk_ids={"a"}, media={"m1": 20.0})
    assert needle in str(e.value)


def test_batch_reports_the_failing_op_and_changes_nothing():
    d = doc()
    with pytest.raises(InputInvalid) as e:
        tl.apply_all(d, [{"type": "track.set", "track": "captions", "fields": {"enabled": True}}, {"type": "x"}], source_s=SRC)
    assert str(e.value).startswith("Op 1 (x)")
    assert d == doc()


def random_op(d, rng):
    vids = d["video"]
    c = rng.choice(vids)
    kind = rng.choice(["split", "delete", "move", "trim", "voice", "track", "music", "music_set"])
    if kind == "split":
        return {"type": "video.split", "clip_id": c["id"], "at_src": round(rng.uniform(c["src_in"], c["src_out"]), 2)}
    if kind == "delete":
        return {"type": "video.delete", "clip_id": c["id"]}
    if kind == "move":
        return {"type": "video.move", "clip_id": c["id"], "index": rng.randrange(len(vids))}
    if kind == "trim":
        return {"type": "video.trim", "clip_id": c["id"], "src_in": c["src_in"] + 0.1, "src_out": c["src_out"]}
    if kind == "voice":
        return {"type": "voice.set", "chunk_id": rng.choice("abc"),
                "fields": {"offset": round(rng.uniform(-2, 2), 2), "muted": rng.random() < 0.3}}
    if kind == "track":
        return {"type": "track.set", "track": "original_audio", "fields": {"gain_db": rng.randint(-30, 0), "auto_duck": rng.random() < 0.5}}
    if kind == "music" or not d["music"]["clips"]:
        return {"type": "music.add", "clip": {"media_id": "m1", "t": rng.uniform(0, 10)}}
    return {"type": "music.set", "clip_id": rng.choice(d["music"]["clips"])["id"], "fields": {"fade_in": 1.5}}


def test_every_op_is_undone_by_its_inverse():
    rng = random.Random(7)
    checked = 0
    for _ in range(40):
        d, history = doc(), []
        for _ in range(25):
            op = random_op(d, rng)
            try:
                nd, inv = ap(d, op, media={"m1": 20.0})
            except InputInvalid:
                continue
            back, _ = ap(nd, inv, media={"m1": 20.0})
            assert tl.layout(back, [chunk(x, i, 3.0 * i + 1) for i, x in enumerate("abc")])[0] == \
                tl.layout(d, [chunk(x, i, 3.0 * i + 1) for i, x in enumerate("abc")])[0]
            assert _norm(back) == _norm(d), op
            history.append((d, inv))
            d = nd
            checked += 1
        for before, inv in reversed(history):                 # undo the whole session
            d, _ = ap(d, inv, media={"m1": 20.0})
            assert _norm(d) == _norm(before)
    assert checked > 300


def _norm(d):
    """Equality up to defaulted voice clips (setting a field back to its default creates the entry)."""
    out = {k: v for k, v in d.items() if k != "voice"}
    out["voice"] = {"gain_db": d["voice"]["gain_db"],
                    "clips": {c: tl.voice_clip(d, c) for c in sorted(set(d["voice"]["clips"]) | set("abc"))}}
    return out
