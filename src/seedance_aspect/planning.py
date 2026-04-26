"""Segment planning and aspect-ratio decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

from seedance_aspect.errors import ConfigError

SUPPORTED_TARGETS = {"9:16", "16:9", "auto-opposite"}


@dataclass
class SegmentPlan:
    index: int
    start: float
    duration: float
    reference_duration: float
    generation_duration: int

    @property
    def pad_seconds(self) -> float:
        return max(0.0, self.reference_duration - self.duration)


def infer_source_orientation(width: int, height: int) -> str:
    return "horizontal" if width >= height else "vertical"


def choose_target_ratio(width: int, height: int, target: str) -> str:
    if target not in SUPPORTED_TARGETS:
        raise ConfigError("target 仅支持 9:16、16:9、auto-opposite。")
    if target != "auto-opposite":
        return target
    return "9:16" if infer_source_orientation(width, height) == "horizontal" else "16:9"


def plan_segments(
    duration: float,
    *,
    max_segment_seconds: int = 15,
    min_reference_seconds: float = 2.0,
    min_generation_seconds: int = 4,
) -> List[SegmentPlan]:
    if duration <= 0:
        raise ConfigError("视频时长必须大于 0。")
    if max_segment_seconds < 2 or max_segment_seconds > 15:
        raise ConfigError("--segment-seconds 必须位于 2 到 15 秒之间。")

    if duration <= max_segment_seconds:
        source_durations = [duration]
    else:
        count = int(math.ceil(duration / max_segment_seconds))
        avg = duration / count
        source_durations = [avg for _ in range(count)]

    plans: List[SegmentPlan] = []
    start = 0.0
    for index, raw_duration in enumerate(source_durations):
        if index == len(source_durations) - 1:
            seg_duration = max(0.001, duration - start)
        else:
            seg_duration = raw_duration
        reference_duration = max(seg_duration, min_reference_seconds)
        generation_duration = int(math.ceil(max(seg_duration, min_generation_seconds)))
        generation_duration = max(min_generation_seconds, min(15, generation_duration))
        plans.append(
            SegmentPlan(
                index=index,
                start=start,
                duration=seg_duration,
                reference_duration=reference_duration,
                generation_duration=generation_duration,
            )
        )
        start += seg_duration
    return plans

