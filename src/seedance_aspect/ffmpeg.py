"""FFmpeg and ffprobe helpers."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import httpx

from seedance_aspect.errors import FFmpegError, NetworkError
from seedance_aspect.planning import SegmentPlan


@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def run_process(args: List[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise FFmpegError(f"命令不存在：{args[0]}。请安装 FFmpeg 并确保在 PATH 中。") from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"命令超时：{' '.join(args[:8])}") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[-1200:]
        raise FFmpegError(f"{args[0]} 执行失败，退出码 {result.returncode}：{stderr}")
    return result


def _parse_fps(raw: str) -> float:
    if not raw or raw == "0/0":
        return 24.0
    if "/" in raw:
        num, den = raw.split("/", 1)
        try:
            return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return 24.0
    try:
        return float(raw)
    except ValueError:
        return 24.0


def probe_video(path: Path) -> VideoInfo:
    result = run_process(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_entries",
            "stream=index,codec_type,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        timeout=60,
    )
    try:
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        streams = data.get("streams", [])
        video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
        return VideoInfo(
            duration=duration,
            width=int(video_stream["width"]),
            height=int(video_stream["height"]),
            fps=_parse_fps(str(video_stream.get("r_frame_rate", "24/1"))),
            has_audio=has_audio,
        )
    except (KeyError, StopIteration, ValueError, json.JSONDecodeError) as exc:
        raise FFmpegError(f"无法解析视频信息：{path}") from exc


def get_duration(path: Path) -> float:
    return probe_video(path).duration


def _reference_filter(plan: SegmentPlan) -> str:
    filters = [
        f"trim=duration={plan.duration:.3f}",
        "setpts=PTS-STARTPTS",
        "fps=24",
        "scale=w='if(gte(iw,ih),1280,720)':h='if(gte(iw,ih),720,1280)':force_original_aspect_ratio=decrease:force_divisible_by=2",
    ]
    if plan.pad_seconds > 0.001:
        filters.append(f"tpad=stop_mode=clone:stop_duration={plan.pad_seconds:.3f}")
    return ",".join(filters)


def extract_reference_segment(input_video: Path, output_path: Path, plan: SegmentPlan) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_process(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{plan.start:.3f}",
            "-t",
            f"{plan.reference_duration:.3f}",
            "-i",
            str(input_video),
            "-vf",
            _reference_filter(plan),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "26",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        timeout=900,
    )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise FFmpegError(f"未生成参考片段：{output_path}")
    return output_path


def align_generated_segment(input_video: Path, output_path: Path, target_duration: float) -> Path:
    current_duration = get_duration(input_video)
    if current_duration <= 0:
        raise FFmpegError(f"生成片段时长无效：{input_video}")
    scale = target_duration / current_duration
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_process(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_video),
            "-vf",
            f"setpts={scale:.10f}*PTS,fps=24",
            "-t",
            f"{target_duration:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        timeout=900,
    )
    return output_path


def concat_videos(video_paths: List[Path], output_path: Path) -> Path:
    if not video_paths:
        raise FFmpegError("没有可拼接的视频片段。")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = output_path.parent / "_concat_list.txt"
    try:
        with list_file.open("w", encoding="utf-8") as handle:
            for item in video_paths:
                handle.write(f"file '{item.resolve()}'\n")
        run_process(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-an",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            timeout=1200,
        )
    finally:
        list_file.unlink(missing_ok=True)
    return output_path


def mux_original_audio(video_path: Path, source_video: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_info = probe_video(source_video)
    if not source_info.has_audio:
        if video_path != output_path:
            output_path.write_bytes(video_path.read_bytes())
        return output_path
    run_process(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(source_video),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ],
        timeout=900,
    )
    return output_path


def download_file(url: str, output_path: Path, *, timeout: int = 600) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            with output_path.open("wb") as handle:
                for chunk in response.iter_bytes():
                    if chunk:
                        handle.write(chunk)
    except httpx.HTTPError as exc:
        raise NetworkError(f"下载生成视频失败：{exc}") from exc
    if output_path.stat().st_size == 0:
        raise NetworkError(f"下载结果为空：{url}")
    return output_path
