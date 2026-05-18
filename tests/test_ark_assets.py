import json

import httpx

from seedance_aspect.ark_assets import ArkAssetsClient
from seedance_aspect.config import ArkAssetsConfig


class RecordingHttpClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, *, content, headers):
        self.calls.append({"url": url, "content": content, "headers": headers})
        return self.response

    def close(self):
        pass


def test_assets_client_signs_action_query_and_reads_result():
    response = httpx.Response(
        200,
        json={
            "ResponseMetadata": {"RequestId": "req-1"},
            "Result": {"Items": [{"Id": "group-1", "Name": "demo"}]},
        },
    )
    http_client = RecordingHttpClient(response)
    client = ArkAssetsClient(
        ArkAssetsConfig(access_key="ak", secret_key="sk"),
        http_client=http_client,
    )

    result = client.call("ListAssetGroups", {"Filter": {"GroupType": "AIGC"}})

    call = http_client.calls[0]
    assert "Action=ListAssetGroups" in call["url"]
    assert "Version=2024-01-01" in call["url"]
    assert call["headers"]["Authorization"].startswith("HMAC-SHA256 Credential=ak/")
    assert call["headers"]["X-Content-Sha256"]
    assert json.loads(call["content"]) == {"Filter": {"GroupType": "AIGC"}}
    assert result["Items"][0]["Id"] == "group-1"


def test_wait_asset_active_returns_failed_error():
    class FakeAssetsClient(ArkAssetsClient):
        def __init__(self):
            super().__init__(ArkAssetsConfig(access_key="ak", secret_key="sk"))

        def get_asset(self, asset_id, *, project_name=None):
            return {
                "Id": asset_id,
                "Status": "Failed",
                "Error": {"Code": "InvalidAsset", "Message": "素材不可用"},
            }

    result = FakeAssetsClient().wait_asset_active("Asset-1", interval_s=0, max_wait_s=0)

    assert result.status == "Failed"
    assert "素材不可用" in result.error_message
