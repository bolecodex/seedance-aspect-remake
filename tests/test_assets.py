import json
from pathlib import Path

from seedance_aspect.assets import load_asset_map


def test_load_asset_map_global_and_segment_references(tmp_path: Path):
    path = tmp_path / "assets.json"
    path.write_text(
        json.dumps(
            {
                "global_references": [
                    {
                        "uri": "asset://asset-global",
                        "media_type": "image",
                        "label": "主角",
                    }
                ],
                "segment_references": {
                    "2": [
                        {
                            "uri": "asset://asset-shot",
                            "media_type": "video",
                            "role": "reference_video",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    asset_map = load_asset_map(path)

    refs = asset_map.references_for(2)
    assert asset_map.has_references is True
    assert refs[0].role == "reference_image"
    assert refs[0].media_type == "image"
    assert refs[1].role == "reference_video"
    assert refs[1].media_type == "video"


def test_load_asset_map_from_environment(monkeypatch, tmp_path: Path):
    path = tmp_path / "assets.json"
    path.write_text('{"global_references":["asset://asset-global"]}', encoding="utf-8")
    monkeypatch.setenv("SEEDANCE_ASSET_MAP", str(path))

    asset_map = load_asset_map(None)

    assert asset_map.references_for(0)[0].uri == "asset://asset-global"
    assert asset_map.references_for(0)[0].role == "reference_image"
