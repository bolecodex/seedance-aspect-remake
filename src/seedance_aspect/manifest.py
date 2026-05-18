"""Manifest contract between split, remake, merge, and status commands."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from seedance_aspect.errors import ManifestError

MANIFEST_VERSION = 2


@dataclass
class MediaReference:
    uri: str
    media_type: str = "image"
    role: str = "reference_image"
    label: str = ""

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MediaReference":
        return cls(
            uri=str(raw.get("uri") or raw.get("url") or ""),
            media_type=str(raw.get("media_type") or raw.get("type") or "image"),
            role=str(raw.get("role") or ""),
            label=str(raw.get("label") or ""),
        ).normalized()

    def normalized(self) -> "MediaReference":
        media_type = self.media_type.strip().lower()
        role = self.role.strip()
        if media_type not in {"image", "video", "audio"}:
            raise ManifestError(f"不支持的素材类型：{self.media_type}")
        if not role:
            role = "reference_video" if media_type == "video" else "reference_image"
        allowed_roles = {
            "image": {"reference_image", "first_frame", "last_frame"},
            "video": {"reference_video"},
            "audio": {"reference_audio"},
        }
        if role not in allowed_roles[media_type]:
            raise ManifestError(f"{media_type} 素材不支持 role={role}")
        if not self.uri:
            raise ManifestError("素材 URI 不能为空。")
        return MediaReference(uri=self.uri, media_type=media_type, role=role, label=self.label)


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
    references: List[MediaReference] = field(default_factory=list)
    continuity_group: int = 0
    continuity_from_previous: bool = False
    cut_reason: str = "uniform"
    first_frame_uri: Optional[str] = None
    api_last_frame_url: Optional[str] = None
    final_last_frame_path: Optional[str] = None
    final_last_frame_uri: Optional[str] = None
    final_last_frame_asset_id: Optional[str] = None
    final_last_frame_asset_uri: Optional[str] = None
    final_last_frame_asset_status: Optional[str] = None
    final_last_frame_asset_error: Optional[str] = None
    asset_id: Optional[str] = None
    asset_uri: Optional[str] = None
    asset_status: Optional[str] = None
    asset_source_url: Optional[str] = None
    asset_error: Optional[str] = None
    task_id: Optional[str] = None
    generated_url: Optional[str] = None
    remade_path: Optional[str] = None
    status: str = "pending"
    attempts: int = 0
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "SegmentEntry":
        data = dict(raw)
        references = data.pop("references", []) or []
        entry = cls(**data)
        entry.references = [
            item if isinstance(item, MediaReference) else MediaReference.from_dict(item)
            for item in references
        ]
        return entry


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
    source_reference_mode: str = "tos"
    split_strategy: str = "uniform"
    scene_threshold: float = 0.28
    continuity: str = "always"
    reference_audio: bool = True
    generation_duration_mode: str = "ceil"
    alignment_mode: str = "speed"
    asset_map_path: Optional[str] = None
    asset_group_id: Optional[str] = None
    asset_project_name: str = "default"
    auto_asset_ingest: bool = False
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

        version = int(raw.get("version", 1))
        if version not in {1, MANIFEST_VERSION}:
            raise ManifestError(f"不支持的 manifest 版本：{version}")
        segments = [SegmentEntry.from_dict(item) for item in raw.pop("segments", [])]
        if version == 1 and "continuity" not in raw:
            raw["continuity"] = "off"
        raw["version"] = MANIFEST_VERSION
        return cls(**raw, segments=segments)

    def succeeded_segments(self) -> List[SegmentEntry]:
        return [seg for seg in self.segments if seg.status == "succeeded"]

    def pending_segments(self) -> List[SegmentEntry]:
        return [seg for seg in self.segments if seg.status in ("pending", "failed", "running")]
