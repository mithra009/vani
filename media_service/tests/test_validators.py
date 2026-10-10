"""Pure helpers: upload validation, quota, storage keys, backoff, status rollup."""

import pytest

from media_service.validators import (
    ValidationError,
    asset_rollup,
    attempts_exhausted,
    backoff_seconds,
    build_storage_key,
    check_quota,
    new_asset_id,
    normalize_filename,
    validate_init,
)
from media_service.config import (
    ASSET_MAX_COUNT,
    ASSET_MAX_TOTAL_BYTES,
    MAX_UPLOAD_BYTES,
    MAX_VIDEO_SECONDS,
)


class TestFilenames:
    def test_plain_name_kept(self):
        assert normalize_filename("My Clip 2.mp4") == "My Clip 2.mp4"

    def test_path_is_stripped(self):
        assert normalize_filename("../../evil.mp4") == "evil.mp4"
        assert normalize_filename("C:\\Users\\x\\clip.mov") == "clip.mov"

    def test_extension_lowercased_in_key_only(self):
        # display name keeps its casing; the key builder lowercases the extension
        assert normalize_filename("Clip.MKV") == "Clip.MKV"
        assert build_storage_key("u", "a", "Clip.MKV").endswith("source.mkv")

    def test_unicode_names_allowed(self):
        assert normalize_filename("கிளிப் ஒன்று.mp4") == "கிளிப் ஒன்று.mp4"

    @pytest.mark.parametrize("name", ["", "   ", "clip.avi", "clip.pdf", ".mp4", "a\x00b.mp4"])
    def test_bad_names_rejected(self, name):
        with pytest.raises(ValidationError):
            normalize_filename(name)


class TestInitValidation:
    def test_ok(self):
        out = validate_init("clip.mp4", 1000, 60_000)
        assert out == {"original_filename": "clip.mp4", "size_bytes": 1000, "duration_ms": 60_000}

    def test_duration_optional(self):
        assert validate_init("clip.mp4", 1000, None)["duration_ms"] is None

    def test_too_big(self):
        with pytest.raises(ValidationError):
            validate_init("clip.mp4", MAX_UPLOAD_BYTES + 1, 1000)

    def test_too_long(self):
        with pytest.raises(ValidationError):
            validate_init("clip.mp4", 1000, (MAX_VIDEO_SECONDS + 5) * 1000)

    def test_empty_file(self):
        with pytest.raises(ValidationError):
            validate_init("clip.mp4", 0, 1000)

    def test_non_numeric(self):
        with pytest.raises(ValidationError):
            validate_init("clip.mp4", "lots", 1000)


class TestQuota:
    def test_under_limit_ok(self):
        check_quota(1, 100, 100)

    def test_count_limit(self):
        with pytest.raises(ValidationError):
            check_quota(ASSET_MAX_COUNT, 0, 100)

    def test_bytes_limit(self):
        with pytest.raises(ValidationError):
            check_quota(0, ASSET_MAX_TOTAL_BYTES - 10, 100)


class TestStorageKey:
    def test_opaque_shape(self):
        assert build_storage_key("user-1", "asset-1", "holiday clip.MOV") == \
            "user-1/asset-1/source.mov"

    def test_unique_asset_ids(self):
        assert new_asset_id() != new_asset_id()


class TestRetry:
    def test_backoff_grows(self):
        assert backoff_seconds(1) < backoff_seconds(2) < backoff_seconds(3)
        assert backoff_seconds(1) == 30

    def test_attempts(self):
        assert not attempts_exhausted(1)
        assert attempts_exhausted(99)


class TestRollup:
    def test_all_ready(self):
        assert asset_rollup("READY", "READY", "READY", False) == "READY"

    def test_in_flight(self):
        assert asset_rollup("READY", "RUNNING", "PENDING", False) == "PROCESSING"

    def test_retryable_failure_keeps_processing(self):
        assert asset_rollup("FAILED", "PENDING", "PENDING", False) == "PROCESSING"

    def test_permanent_failure(self):
        assert asset_rollup("READY", "FAILED", "READY", True) == "FAILED"
