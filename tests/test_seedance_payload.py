from seedance_aspect.manifest import MediaReference
from seedance_aspect.seedance import VideoGenerateRequest, normalize_status


def test_video_reference_payload_shape():
    req = VideoGenerateRequest(
        model="doubao-seedance-2-0-260128",
        prompt="保持节奏，只调整比例",
        ratio="9:16",
        duration=8,
        resolution="720p",
        reference_uris=["https://example.com/seg.mp4"],
        safety_identifier="user-hash",
    )
    payload = req.to_payload()
    assert payload["model"] == "doubao-seedance-2-0-260128"
    assert payload["ratio"] == "9:16"
    assert payload["duration"] == 8
    assert payload["resolution"] == "720p"
    assert payload["watermark"] is False
    assert payload["generate_audio"] is False
    assert payload["safety_identifier"] == "user-hash"
    assert payload["content"][1]["type"] == "video_url"
    assert payload["content"][1]["role"] == "reference_video"


def test_multimodal_asset_payload_shape():
    req = VideoGenerateRequest(
        model="doubao-seedance-2-0-260128",
        prompt="保持剧情和节奏",
        ratio="16:9",
        duration=6,
        resolution="720p",
        references=[
            MediaReference(uri="https://tos.example.com/tail.png", media_type="image", role="first_frame"),
            MediaReference(uri="asset://asset-actor", media_type="image", role="reference_image"),
            MediaReference(uri="asset://asset-shot", media_type="video", role="reference_video"),
        ],
        return_last_frame=True,
    )

    payload = req.to_payload()

    assert payload["return_last_frame"] is True
    assert payload["content"][1]["type"] == "image_url"
    assert payload["content"][1]["role"] == "first_frame"
    assert payload["content"][2]["image_url"]["url"] == "asset://asset-actor"
    assert payload["content"][2]["role"] == "reference_image"
    assert payload["content"][3]["video_url"]["url"] == "asset://asset-shot"


def test_auto_duration_payload_shape():
    req = VideoGenerateRequest(
        model="doubao-seedance-2-0-260128",
        prompt="按参考视频音频同步口型",
        ratio="16:9",
        duration=-1,
        resolution="720p",
        reference_uris=["asset://asset-shot"],
    )

    assert req.to_payload()["duration"] == -1


def test_status_normalization():
    assert normalize_status("queued") == "running"
    assert normalize_status("running") == "running"
    assert normalize_status("succeeded") == "succeeded"
    assert normalize_status("expired") == "failed"
