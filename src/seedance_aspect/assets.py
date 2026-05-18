"""Asset map loading for private Ark portrait/video assets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from seedance_aspect.errors import ConfigError
from seedance_aspect.manifest import MediaReference


@dataclass
class AssetMap:
    path: Optional[Path] = None
    global_references: List[MediaReference] = field(default_factory=list)
    segment_references: Dict[int, List[MediaReference]] = field(default_factory=dict)

    @property
    def has_references(self) -> bool:
        return bool(self.global_references or self.segment_references)

    def references_for(self, index: int) -> List[MediaReference]:
        return [*self.global_references, *self.segment_references.get(index, [])]


def load_asset_map(path: Optional[Path]) -> AssetMap:
    selected = path or _env_asset_map_path()
    if selected is None:
        return AssetMap()
    selected = selected.expanduser()
    if not selected.exists():
        raise ConfigError(f"资产清单不存在：{selected}")
    try:
        raw = json.loads(selected.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"资产清单 JSON 无效：{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("资产清单必须是 JSON 对象。")

    globals_raw = raw.get("global_references", []) or []
    if not isinstance(globals_raw, list):
        raise ConfigError("asset-map.global_references 必须是数组。")
    global_references = [_reference_from_raw(item) for item in globals_raw]

    segment_refs: Dict[int, List[MediaReference]] = {}
    segments_raw = raw.get("segment_references", {}) or {}
    if not isinstance(segments_raw, dict):
        raise ConfigError("asset-map.segment_references 必须是对象。")
    for key, items in segments_raw.items():
        try:
            index = int(key)
        except ValueError as exc:
            raise ConfigError(f"segment_references 的 key 必须是片段序号：{key}") from exc
        if not isinstance(items, list):
            raise ConfigError(f"segment_references.{key} 必须是数组。")
        segment_refs[index] = [_reference_from_raw(item) for item in items]

    return AssetMap(
        path=selected,
        global_references=global_references,
        segment_references=segment_refs,
    )


def _env_asset_map_path() -> Optional[Path]:
    raw = os.getenv("SEEDANCE_ASSET_MAP", "").strip()
    return Path(raw) if raw else None


def _reference_from_raw(raw: Any) -> MediaReference:
    if isinstance(raw, str):
        return MediaReference(uri=raw, media_type="image", role="reference_image").normalized()
    if not isinstance(raw, dict):
        raise ConfigError("资产引用必须是对象或 URI 字符串。")
    try:
        return MediaReference.from_dict(raw)
    except Exception as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(str(exc)) from exc
