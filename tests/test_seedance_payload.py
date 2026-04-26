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


def test_status_normalization():
    assert normalize_status("queued") == "running"
    assert normalize_status("running") == "running"
    assert normalize_status("succeeded") == "succeeded"
    assert normalize_status("expired") == "failed"

