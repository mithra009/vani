"""FFmpeg/FFprobe wrappers: argument construction always, real encode when ffmpeg exists."""

import shutil
import subprocess
from pathlib import Path

import pytest

from media_service import media
from media_service.config import PROXY_DURATION_TOLERANCE_S, PROXY_LONGEST_SIDE

HAVE_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")


class TestArgs:
    def test_scale_caps_longest_side_without_upscaling(self):
        f = media.scale_filter(1280)
        assert "min(iw,1280)" in f and "min(ih,1280)" in f
        assert "-2" in f  # even dimensions, aspect preserved

    def test_proxy_args_preserve_timeline(self):
        args = media.proxy_args("in.mp4", "out.mp4")
        assert args[0] == "ffmpeg"
        assert "libx264" in args and "aac" in args
        assert "+faststart" in args
        # Timestamps/orientation: no fps filter, no -noautorotate (auto-rotation stays on).
        assert "fps" not in args
        assert "-noautorotate" not in args
        assert args[-1] == "out.mp4"
        assert media.PROXY_LONGEST_SIDE == PROXY_LONGEST_SIDE

    def test_thumbnail_args(self):
        args = media.thumbnail_args("in.mp4", "thumb.jpg", 1.25)
        assert "-frames:v" in args and "thumb.jpg" in args
        assert "-ss" in args and args[args.index("-ss") + 1] == "1.250"


@needs_ffmpeg
class TestRealFfprobe:
    @pytest.fixture
    def tiny_mp4(self, tmp_path_factory):
        """A real 1-second 128x96 H.264 clip."""
        p = tmp_path_factory.mktemp("media") / "tiny.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             "testsrc=duration=1:size=128x96:rate=10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             str(p)],
            check=True, capture_output=True,
        )
        return p

    def test_probe_reads_stream_info(self, tiny_mp4):
        info = media.probe(str(tiny_mp4))
        assert info["has_video"] is True
        assert 0.9 <= info["duration"] <= 1.2
        assert (info["width"], info["height"]) == (128, 96)

    def test_proxy_output_matches_source_duration(self, tiny_mp4, tmp_path):
        out = tmp_path / "proxy.mp4"
        media.run(media.proxy_args(str(tiny_mp4), str(out)))
        src = media.probe(str(tiny_mp4))
        dst = media.probe(str(out))
        assert out.exists()
        # Duration preserved within tolerance (timeline sync requirement).
        assert abs(dst["duration"] - src["duration"]) <= PROXY_DURATION_TOLERANCE_S
        # No upscaling: 128x96 stays 128x96.
        assert (dst["width"], dst["height"]) == (128, 96)

    def test_thumbnail_written(self, tiny_mp4, tmp_path):
        out = tmp_path / "thumb.jpg"
        media.run(media.thumbnail_args(str(tiny_mp4), str(out), 0.1))
        assert out.exists() and out.stat().st_size > 0

    def test_probe_rejects_garbage(self, tmp_path):
        bad = tmp_path / "bad.mp4"
        bad.write_bytes(b"not a video")
        with pytest.raises(media.MediaError):
            media.probe(str(bad))
