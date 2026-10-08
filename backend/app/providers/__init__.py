"""Speech and language providers. `get()` returns the real Gnani + Gemini pair, or local
fakes when FAKE_PROVIDERS=1 (no network, no credits)."""

from __future__ import annotations

from ..config import FAKE_PROVIDERS


def get():
    if FAKE_PROVIDERS:
        from .fake import FakeLLM, FakeSpeech
        return FakeSpeech(), FakeLLM()
    from .gnani import GnaniSpeech
    from .gemini import GeminiLLM
    return GnaniSpeech(), GeminiLLM()
