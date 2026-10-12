"""Tests for editor_service.placement."""

import pytest

from editor_service.chunking import Chunk, Transcript
from editor_service.placement import Anchor, estimate_seconds, place_script, place_speech, time_at


# ── time_at ──────────────────────────────────────────────────────


class TestTimeAt:
    SPANS = (
        (0, 5, 0.0, 1.0),   # "Hello" chars 0-5, 0s-1s
        (6, 11, 1.5, 2.5),  # "world" chars 6-11, 1.5s-2.5s
    )

    def test_interpolated_within_span(self):
        # char 3 is 60% through first span (0-5), so time = 0.0 + 0.6 * 1.0 = 0.6
        assert time_at(self.SPANS, 3) == pytest.approx(0.6)

    def test_char_before_first_span(self):
        # Char position before first span start → returns first span's start time
        spans = ((5, 10, 2.0, 3.0),)
        assert time_at(spans, 0) == 2.0

    def test_char_after_last_span(self):
        # Char position after last span end → returns last span's end time
        assert time_at(self.SPANS, 20) == 2.5

    def test_raises_on_empty_spans(self):
        with pytest.raises(ValueError, match="No timed segments"):
            time_at((), 0)


# ── place_speech ─────────────────────────────────────────────────


class TestPlaceSpeech:
    def test_simple_two_segment_two_chunk(self):
        t = Transcript(
            text="Hello world",
            spans=((0, 5, 0.0, 1.0), (6, 11, 1.5, 2.5)),
        )
        chunks = [
            Chunk(idx=0, char_start=0, char_end=5, text="Hello", emotion_tag="neutral"),
            Chunk(idx=1, char_start=6, char_end=11, text="world", emotion_tag="neutral"),
        ]
        anchors = place_speech(t, chunks)
        assert len(anchors) == 2
        # First chunk: start=0.0, end=1.0 → len=1.0
        assert anchors[0].start_s == pytest.approx(0.0)
        assert anchors[0].len_s == pytest.approx(1.0)
        assert anchors[0].overflow is False
        # Second chunk: start=1.5, end=2.5 → len=1.0
        assert anchors[1].start_s == pytest.approx(1.5)
        assert anchors[1].len_s == pytest.approx(1.0)


# ── place_script ─────────────────────────────────────────────────


class TestPlaceScript:
    def _chunks(self):
        return [
            Chunk(idx=0, char_start=0, char_end=10, text="0123456789", emotion_tag="neutral"),
            Chunk(idx=1, char_start=11, char_end=21, text="0123456789", emotion_tag="neutral"),
        ]

    def test_flags_overflow(self):
        # Each chunk: 10 chars / (10 cps * 1.0) = 1.0s, gap=0.5s
        # Chunk 0: t=0, len=1.0 → ends at 1.0 (ok if video_s=1.0)
        # Chunk 1: t=1.5, len=1.0 → ends at 2.5 (overflow if video_s=2.0)
        anchors = place_script(self._chunks(), video_s=2.0, cps=10.0, gap_s=0.5)
        assert anchors[0].overflow is False
        assert anchors[1].overflow is True

    def test_no_overflow_with_enough_room(self):
        anchors = place_script(self._chunks(), video_s=100.0, cps=10.0, gap_s=0.5)
        assert all(not a.overflow for a in anchors)


# ── estimate_seconds ─────────────────────────────────────────────


class TestEstimateSeconds:
    def test_basic_calc(self):
        # 10 chars / (5 cps * 2.0 speed) = 1.0 second
        assert estimate_seconds("0123456789", cps=5.0, speed=2.0) == pytest.approx(1.0)

