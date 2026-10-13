"""Placement math and content-key stability."""

from decimal import Decimal

from editor_service import chunking, keys, placement

SEGS = [{"start_s": 1.0, "end_s": 3.0, "text": "aaaa bbbb"}, {"start_s": 5.0, "end_s": 6.0, "text": "cc"}]


def test_speech_anchor_interpolates_within_a_segment():
    t = chunking.build_transcript(SEGS)            # "aaaa bbbb cc"
    cs = chunking.validate(t, [{"text": "aaaa", "emotion_tag": "neutral"},
                               {"text": "bbbb", "emotion_tag": "neutral"},
                               {"text": "cc", "emotion_tag": "neutral"}])
    a = placement.place_speech(t, cs)
    assert a[0].start_s == 1.0 and abs(a[0].len_s - 2 * 4 / 9) < 0.002
    assert abs(a[1].start_s - (1 + 2 * 5 / 9)) < 0.002 and abs(a[1].start_s + a[1].len_s - 3.0) < 0.002
    assert a[2].start_s == 5.0 and a[2].len_s == 1.0


def test_chunk_spanning_segments_covers_the_gap():
    t = chunking.build_transcript(SEGS)
    cs = chunking.validate(t, [{"text": "aaaa bbbb cc", "emotion_tag": "neutral"}])
    a = placement.place_speech(t, cs)[0]
    assert a.start_s == 1.0 and a.len_s == 5.0


def test_script_placement_flags_overflow_not_drops():
    t = chunking.script_transcript("x" * 26 + " " + "y" * 26)
    cs = chunking.validate(t, [{"text": "x" * 26, "emotion_tag": "neutral"}, {"text": "y" * 26, "emotion_tag": "neutral"}])
    a = placement.place_script(cs, video_s=3.0, cps=13.0, gap_s=0.3)
    assert a[0] == placement.Anchor(0.0, 2.0, False)
    assert a[1] == placement.Anchor(2.3, 2.0, True)


def test_tts_key_is_stable_across_speed_types():
    v = {"mode": "persona", "voice_id": "a"}
    assert keys.tts_key("hi", v, "hi-IN", "neutral", 1) == keys.tts_key("hi", v, "hi-IN", "neutral", Decimal("1.000"))
    assert keys.tts_key("hi", v, "hi-IN", "neutral", 1) != keys.tts_key("hi", v, "hi-IN", "laugh", 1)
    assert keys.tts_key("hi", v, "hi-IN", "neutral", 1) != keys.tts_key("hi", {"mode": "persona", "voice_id": "b"}, "hi-IN", "neutral", 1)
