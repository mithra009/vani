"""Gemini chunk validation: cut-only, full coverage, allowed tags — or OutputInvalid."""

import pytest

from editor_service import chunking
from editor_service.errors import OutputInvalid

SEGS = [
    {"start_s": 1.0, "end_s": 3.0, "text": "Hello there."},
    {"start_s": 4.0, "end_s": 8.0, "text": "  This is   a test. Haha!  "},
]


def test_build_transcript_normalises_and_tracks_spans():
    t = chunking.build_transcript(SEGS)
    assert t.text == "Hello there. This is a test. Haha!"
    assert t.spans[0] == (0, 12, 1.0, 3.0)
    assert t.text[t.spans[1][0]:t.spans[1][1]] == "This is a test. Haha!"


def test_build_transcript_skips_empty_segments():
    t = chunking.build_transcript([{"start_s": 0, "end_s": 1, "text": "  "}, *SEGS])
    assert len(t.spans) == 2


def test_valid_chunks():
    t = chunking.build_transcript(SEGS)
    out = chunking.validate(t, [
        {"text": "Hello there.", "emotion_tag": "neutral"},
        {"text": "This is a test.", "emotion_tag": "neutral"},
        {"text": "Haha!", "emotion_tag": "laugh"},
    ])
    assert [c.text for c in out] == ["Hello there.", "This is a test.", "Haha!"]
    assert [(c.char_start, c.char_end) for c in out] == [(0, 12), (13, 28), (29, 34)]
    assert out[2].emotion_tag == "laugh"


def test_whitespace_inside_a_chunk_is_tolerated():
    t = chunking.build_transcript(SEGS)
    out = chunking.validate(t, [{"text": "Hello   there.  This is a test. Haha!", "emotion_tag": "neutral"}])
    assert out[0].char_end == len(t.text)


@pytest.mark.parametrize("raw,needle", [
    ([{"text": "Hello there!", "emotion_tag": "neutral"}, {"text": "This is a test. Haha!", "emotion_tag": "neutral"}], "doesn't continue"),
    ([{"text": "Hello there.", "emotion_tag": "neutral"}], "dropped"),
    ([{"text": "Hello there. This is a test. Haha! Extra", "emotion_tag": "neutral"}], "doesn't continue"),
    ([{"text": "Hello there. This is a test. Haha!", "emotion_tag": "angry"}], "unsupported emotion"),
    ([{"text": "", "emotion_tag": "neutral"}], "empty"),
    ([], "no chunks"),
    ({"text": "x"}, "no chunks"),
    (["Hello"], "malformed"),
])
def test_invalid_output_is_rejected(raw, needle):
    with pytest.raises(OutputInvalid) as e:
        chunking.validate(chunking.build_transcript(SEGS), raw)
    assert needle in str(e.value)
    assert e.value.code == "chunking_invalid"


def test_tts_text_tags():
    assert chunking.tts_text("Hi", "neutral") == "Hi"
    assert chunking.tts_text("Hi", "whispers") == "<whispers> Hi"
