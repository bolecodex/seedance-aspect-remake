from pathlib import Path

from seedance_aspect.manifest import Manifest, SegmentEntry


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
            )
        ],
    )
    manifest.save(path)
    loaded = Manifest.load(path)
    assert loaded.source == manifest.source
    assert loaded.target_ratio == "16:9"
    assert loaded.segments[0].reference_uri == "asset://asset-1"

