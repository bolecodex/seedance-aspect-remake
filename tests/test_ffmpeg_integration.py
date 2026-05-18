import shutil
import subprocess
from pathlib import Path

import pytest

from seedance_aspect.ffmpeg import (
    align_generated_segment,
    detect_scene_cuts,
    extract_last_frame,
    extract_reference_segment,
    probe_video,
)
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
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "2.5",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
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
    assert info.has_audio is True

    align_generated_segment(reference, aligned, 1.5)
    aligned_info = probe_video(aligned)
    assert 1.40 <= aligned_info.duration <= 1.65

    last_frame = tmp_path / "tail.png"
    extract_last_frame(aligned, last_frame)
    assert last_frame.exists()


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg unavailable")
def test_ffmpeg_detects_scene_cut(tmp_path: Path):
    source = tmp_path / "scene.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:size=320x180:rate=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:size=320x180:rate=24:d=1",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
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

    cuts = detect_scene_cuts(source, threshold=0.2)

    assert any(0.8 <= cut <= 1.2 for cut in cuts)
