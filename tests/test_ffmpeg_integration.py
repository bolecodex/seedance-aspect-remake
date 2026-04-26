import shutil
import subprocess
from pathlib import Path

import pytest

from seedance_aspect.ffmpeg import align_generated_segment, extract_reference_segment, probe_video
from seedance_aspect.planning import SegmentPlan


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg unavailable")
def test_ffmpeg_reference_and_align(tmp_path: Path):
    source = tmp_path / "source.mp4"
    reference = tmp_path / "reference.mp4"
    aligned = tmp_path / "aligned.mp4"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=24",
            "-t",
            "2.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    plan = SegmentPlan(index=0, start=0.0, duration=1.5, reference_duration=2.0, generation_duration=4)
    extract_reference_segment(source, reference, plan)
    info = probe_video(reference)
    assert info.duration >= 1.9

    align_generated_segment(reference, aligned, 1.5)
    aligned_info = probe_video(aligned)
    assert 1.40 <= aligned_info.duration <= 1.65

