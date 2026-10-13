"""Tests for editor_service.keys."""

from decimal import Decimal

from editor_service.keys import artifact_path, h, speed_str, tts_key


# ── h() ──────────────────────────────────────────────────────────


class TestH:
    def test_same_input_same_hash(self):
        assert h("a", "b") == h("a", "b")

    def test_different_input_different_hash(self):
        assert h("a") != h("b")


# ── speed_str ────────────────────────────────────────────────────


class TestSpeedStr:
    def test_normalises_to_same_string(self):
        a = speed_str(1.0)
        b = speed_str(1.000)
        c = speed_str(Decimal("1.000"))
        assert a == b == c == "1.000"


# ── tts_key ──────────────────────────────────────────────────────


class TestTtsKey:
    def test_stability_same_inputs(self):
        voice = {"mode": "persona", "voice_id": "v1"}
        k1 = tts_key("hello", voice, "hi-IN", "neutral", 1.0)
        k2 = tts_key("hello", voice, "hi-IN", "neutral", 1.0)
        assert k1 == k2

    def test_different_text_different_key(self):
        voice = {"mode": "persona", "voice_id": "v1"}
        k1 = tts_key("hello", voice, "hi-IN", "neutral", 1.0)
        k2 = tts_key("world", voice, "hi-IN", "neutral", 1.0)
        assert k1 != k2


# ── artifact_path ────────────────────────────────────────────────


class TestArtifactPath:
    def test_format(self):
        result = artifact_path("user123", "tts", "abc", "wav")
        assert result == "user123/artifacts/tts/abc.wav"

