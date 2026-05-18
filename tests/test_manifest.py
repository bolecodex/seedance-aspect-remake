from pathlib import Path

import json

from seedance_aspect.manifest import Manifest, MediaReference, SegmentEntry


def test_manifest_round_trip(tmp_path: Path):
    path = tmp_path / "manifest.json"
    manifest = Manifest(
        source="/tmp/input.mp4",
        target_ratio="16:9",
        prompt="保持节奏",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=8,
                reference_duration=8,
                generation_duration=8,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
                reference_uri="asset://asset-1",
                references=[
                    MediaReference(uri="asset://asset-image", media_type="image", role="reference_image")
                ],
                continuity_group=3,
                api_last_frame_url="https://example.com/tail.png",
            )
        ],
    )
    manifest.save(path)
    loaded = Manifest.load(path)
    assert loaded.source == manifest.source
    assert loaded.target_ratio == "16:9"
    assert loaded.continuity == "always"
    assert loaded.segments[0].reference_uri == "asset://asset-1"
    assert loaded.segments[0].references[0].role == "reference_image"
    assert loaded.segments[0].api_last_frame_url == "https://example.com/tail.png"


def test_manifest_loads_v1_with_defaults(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "source": "/tmp/input.mp4",
                "target_ratio": "9:16",
                "prompt": "保持节奏",
                "model": "doubao-seedance-2-0-260128",
                "resolution": "720p",
                "segment_seconds": 15,
                "keep_audio": True,
                "segments": [
                    {
                        "index": 0,
                        "start": 0,
                        "duration": 5,
                        "reference_duration": 5,
                        "generation_duration": 5,
                        "source_path": "references/000.mp4",
                        "reference_path": "references/000.mp4",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = Manifest.load(path)

    assert loaded.version == 2
    assert loaded.source_reference_mode == "tos"
    assert loaded.continuity == "off"
    assert loaded.segments[0].references == []
