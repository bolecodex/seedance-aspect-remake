"""Segment planning and aspect-ratio decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

from seedance_aspect.errors import ConfigError

SUPPORTED_TARGETS = {"9:16", "16:9", "auto-opposite"}
SUPPORTED_SPLIT_STRATEGIES = {"uniform", "scene"}
SUPPORTED_CONTINUITY = {"scene-tail", "always", "off"}
SUPPORTED_GENERATION_DURATION_MODES = {"ceil", "auto"}


@dataclass
class SegmentPlan:
    index: int
    start: float
    duration: float
    reference_duration: float
    generation_duration: int
    continuity_group: int = 0
    continuity_from_previous: bool = False
    cut_reason: str = "uniform"

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
    generation_duration_mode: str = "ceil",
) -> List[SegmentPlan]:
    if duration <= 0:
        raise ConfigError("视频时长必须大于 0。")
    if max_segment_seconds < 2 or max_segment_seconds > 15:
        raise ConfigError("--segment-seconds 必须位于 2 到 15 秒之间。")
    generation_duration_mode = validate_generation_duration_mode(generation_duration_mode)

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
        plans.append(
            SegmentPlan(
                index=index,
                start=start,
                duration=seg_duration,
                reference_duration=reference_duration,
                generation_duration=_generation_duration(
                    seg_duration,
                    min_generation_seconds,
                    generation_duration_mode,
                ),
                continuity_group=0,
                continuity_from_previous=index > 0,
                cut_reason="uniform",
            )
        )
        start += seg_duration
    return plans


def validate_split_strategy(value: str) -> str:
    if value not in SUPPORTED_SPLIT_STRATEGIES:
        raise ConfigError("split-strategy 仅支持 scene、uniform。")
    return value


def validate_continuity(value: str) -> str:
    if value not in SUPPORTED_CONTINUITY:
        raise ConfigError("continuity 仅支持 scene-tail、always、off。")
    return value


def validate_generation_duration_mode(value: str) -> str:
    if value not in SUPPORTED_GENERATION_DURATION_MODES:
        raise ConfigError("generation-duration-mode 仅支持 auto、ceil。")
    return value


def plan_scene_segments(
    duration: float,
    scene_cuts: List[float],
    *,
    max_segment_seconds: int = 15,
    min_reference_seconds: float = 2.0,
    min_generation_seconds: int = 4,
    generation_duration_mode: str = "ceil",
) -> List[SegmentPlan]:
    if duration <= 0:
        raise ConfigError("视频时长必须大于 0。")
    if max_segment_seconds < 2 or max_segment_seconds > 15:
        raise ConfigError("--segment-seconds 必须位于 2 到 15 秒之间。")
    generation_duration_mode = validate_generation_duration_mode(generation_duration_mode)

    cuts = sorted(
        {
            round(cut, 3)
            for cut in scene_cuts
            if min_reference_seconds <= cut <= duration - min_reference_seconds
        }
    )
    if duration <= max_segment_seconds:
        return [
            _make_plan(
                0,
                0.0,
                duration,
                min_reference_seconds,
                min_generation_seconds,
                generation_duration_mode,
            )
        ]

    boundaries = [0.0]
    cut_reasons: List[str] = []
    current = 0.0
    while duration - current > max_segment_seconds:
        max_end = min(duration, current + max_segment_seconds)
        candidates = [
            cut
            for cut in cuts
            if current + min_reference_seconds <= cut <= max_end
            and duration - cut >= min_reference_seconds
        ]
        if candidates:
            next_end = candidates[-1]
            reason = "scene"
        else:
            next_end = max_end
            reason = "internal"
        if next_end <= current:
            next_end = max_end
            reason = "internal"
        boundaries.append(next_end)
        cut_reasons.append(reason)
        current = next_end

    if boundaries[-1] < duration:
        tail = duration - boundaries[-1]
        if (
            tail < min_generation_seconds
            and len(boundaries) >= 2
            and duration - boundaries[-2] <= max_segment_seconds
        ):
            boundaries[-1] = duration
            if cut_reasons:
                cut_reasons[-1] = "tail_merged"
        else:
            boundaries.append(duration)
            cut_reasons.append("tail")

    plans: List[SegmentPlan] = []
    group = 0
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        previous_reason = cut_reasons[index - 1] if index > 0 and index - 1 < len(cut_reasons) else ""
        continues = previous_reason == "internal"
        if index > 0 and not continues:
            group += 1
        plan = _make_plan(
            index,
            start,
            max(0.001, end - start),
            min_reference_seconds,
            min_generation_seconds,
            generation_duration_mode,
        )
        plan.continuity_group = group
        plan.continuity_from_previous = continues
        plan.cut_reason = cut_reasons[index] if index < len(cut_reasons) else "tail"
        plans.append(plan)
    return plans


def _make_plan(
    index: int,
    start: float,
    duration: float,
    min_reference_seconds: float,
    min_generation_seconds: int,
    generation_duration_mode: str = "ceil",
) -> SegmentPlan:
    reference_duration = max(duration, min_reference_seconds)
    return SegmentPlan(
        index=index,
        start=start,
        duration=duration,
        reference_duration=reference_duration,
        generation_duration=_generation_duration(duration, min_generation_seconds, generation_duration_mode),
    )


def _generation_duration(
    duration: float,
    min_generation_seconds: int,
    generation_duration_mode: str,
) -> int:
    if generation_duration_mode == "auto" and duration >= min_generation_seconds:
        return -1
    generation_duration = int(math.ceil(max(duration, min_generation_seconds)))
    return max(min_generation_seconds, min(15, generation_duration))
