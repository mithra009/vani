"""config/limits.toml loader: env > file > default, unit scaling, and loud failure on bad values."""

import importlib

import pytest


def load(monkeypatch, tmp_path, text, **env):
    f = tmp_path / "limits.toml"
    f.write_text(text, encoding="utf-8")
    monkeypatch.setenv("VANI_LIMITS_FILE", str(f))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from media_service import limits
    return importlib.reload(limits)


def test_file_value_used_and_scaled(monkeypatch, tmp_path):
    lim = load(monkeypatch, tmp_path, "[uploads]\nmax_upload_mb = 250\n")
    assert lim.limit("uploads", "max_upload_mb", 500_000_000, "NOPE_UNSET", scale=1_000_000) == 250_000_000


def test_env_overrides_file(monkeypatch, tmp_path):
    lim = load(monkeypatch, tmp_path, "[providers]\ngnani_tts_per_min = 60\n", GNANI_TTS_RPM="120")
    assert lim.limit("providers", "gnani_tts_per_min", 60, "GNANI_TTS_RPM") == 120


def test_default_when_missing(monkeypatch, tmp_path):
    lim = load(monkeypatch, tmp_path, "")
    assert lim.limit("projects", "max_per_user", 50, "NOPE_UNSET") == 50


@pytest.mark.parametrize("text", ["[projects]\nmax_per_user = -1\n", "[projects]\nmax_per_user = \"lots\"\n"])
def test_bad_values_fail_loudly(monkeypatch, tmp_path, text):
    lim = load(monkeypatch, tmp_path, text)
    with pytest.raises(RuntimeError, match="max_per_user"):
        lim.limit("projects", "max_per_user", 50, "NOPE_UNSET")


def test_malformed_file_fails_at_load(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="not valid TOML"):
        load(monkeypatch, tmp_path, "[projects\nmax_per_user = 1\n")


def test_repo_file_is_valid(monkeypatch):
    monkeypatch.delenv("VANI_LIMITS_FILE", raising=False)
    from media_service import limits
    lim = importlib.reload(limits)
    assert lim._FILE["providers"]["gnani_tts_per_min"] > 0
