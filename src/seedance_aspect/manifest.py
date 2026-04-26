"""Manifest contract between split, remake, merge, and status commands."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from seedance_aspect.errors import ManifestError

MANIFEST_VERSION = 1


@dataclass
class SegmentEntry:
    index: int
    start: float
    duration: float
    reference_duration: float
    generation_duration: int
    source_path: str
    reference_path: str
    reference_uri: Optional[str] = None
    task_id: Optional[str] = None
    generated_url: Optional[str] = None
    remade_path: Optional[str] = None
    status: str = "pending"
    attempts: int = 0
    error: Optional[str] = None


@dataclass
class Manifest:
    version: int = MANIFEST_VERSION
    source: str = ""
    target_ratio: str = "9:16"
    prompt: str = ""
    model: str = "doubao-seedance-2-0-260128"
    resolution: str = "720p"
    segment_seconds: int = 15
    keep_audio: bool = True
    segments: List[SegmentEntry] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        if not path.exists():
            raise ManifestError(f"Manifest 不存在：{path}")
        try:
            raw: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestError(f"Manifest JSON 无效：{exc}") from exc

        version = int(raw.get("version", 0))
        if version != MANIFEST_VERSION:
            raise ManifestError(f"不支持的 manifest 版本：{version}")
        segments = [SegmentEntry(**item) for item in raw.pop("segments", [])]
        return cls(**raw, segments=segments)

    def succeeded_segments(self) -> List[SegmentEntry]:
        return [seg for seg in self.segments if seg.status == "succeeded"]

    def pending_segments(self) -> List[SegmentEntry]:
        return [seg for seg in self.segments if seg.status in ("pending", "failed", "running")]

