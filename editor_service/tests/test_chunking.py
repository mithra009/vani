"""Tests for editor_service.chunking."""

import pytest

from editor_service.chunking import (
    Chunk,
    Transcript,
    build_transcript,
    locate,
    script_transcript,
    tts_text,
    validate,
)
from editor_service.errors import OutputInvalid


# ── build_transcript ─────────────────────────────────────────────


class TestBuildTranscript:
    def test_joins_segments_with_spaces_and_correct_spans(self):
        segments = [
            {"text": "Hello", "start_s": 0.0, "end_s": 1.0},
            {"text": "world", "start_s": 1.5, "end_s": 2.0},
        ]
        t = build_transcript(segments)
        assert t.text == "Hello world"
        # First span: chars 0-5, second span: chars 6-11
        assert t.spans == ((0, 5, 0.0, 1.0), (6, 11, 1.5, 2.0))


# ── script_transcript ───────────────────────────────────────────


class TestScriptTranscript:
    def test_produces_text_with_no_spans(self):
        t = script_transcript("  Hello   world  ")
        assert t.text == "Hello world"
        assert t.spans == ()


# ── locate ───────────────────────────────────────────────────────


class TestLocate:
    def test_succeeds_on_valid_contiguous_pieces(self):
        transcript = "Hello world foo"
        result = locate(transcript, ["Hello", "world foo"])
        assert result == [(0, 5), (6, 15)]

    def test_raises_on_empty_piece(self):
        with pytest.raises(OutputInvalid, match="empty"):
            locate("Hello world", ["Hello", ""])

    def test_raises_on_piece_not_matching(self):
        with pytest.raises(OutputInvalid, match="doesn't continue"):
            locate("Hello world", ["Hello", "xyz"])

    def test_raises_when_pieces_stop_early(self):
        with pytest.raises(OutputInvalid, match="stop early"):
            locate("Hello world", ["Hello"])


# ── validate ─────────────────────────────────────────────────────


class TestValidate:
    def _transcript(self) -> Transcript:
        return build_transcript([
            {"text": "Hello", "start_s": 0.0, "end_s": 1.0},
            {"text": "world", "start_s": 1.5, "end_s": 2.0},
        ])

    def test_valid_chunks(self):
        t = self._transcript()
        raw = [
            {"text": "Hello", "emotion_tag": "neutral"},
            {"text": "world", "emotion_tag": "laugh"},
        ]
        chunks = validate(t, raw)
        assert len(chunks) == 2
        assert chunks[0] == Chunk(idx=0, char_start=0, char_end=5, text="Hello", emotion_tag="neutral")
        assert chunks[1] == Chunk(idx=1, char_start=6, char_end=11, text="world", emotion_tag="laugh")

    def test_rejects_malformed_item(self):
        t = self._transcript()
        with pytest.raises(OutputInvalid, match="malformed"):
            validate(t, ["not a dict"])

    def test_rejects_unsupported_emotion_tag(self):
        t = self._transcript()
        raw = [
            {"text": "Hello world", "emotion_tag": "angry"},
        ]
        with pytest.raises(OutputInvalid, match="unsupported emotion tag"):
            validate(t, raw)

    def test_rejects_empty_list(self):
        t = self._transcript()
        with pytest.raises(OutputInvalid, match="no chunks"):
            validate(t, [])


# ── tts_text ─────────────────────────────────────────────────────


class TestTtsText:
    def test_prepends_emotion_tag_when_not_neutral(self):
        assert tts_text("Hello", "laugh") == "<laugh> Hello"

    def test_returns_plain_text_when_neutral(self):
        assert tts_text("Hello", "neutral") == "Hello"

