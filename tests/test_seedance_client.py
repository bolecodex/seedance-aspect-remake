from seedance_aspect.seedance import SeedanceClient, VideoGenerateRequest


class FakeArk:
    def __init__(self):
        self.payload = None

    def post(self, endpoint, payload):
        self.payload = payload
        return {"id": "task-123"}, "req-submit"

    def get(self, endpoint):
        return (
            {
                "data": {
                    "status": "succeeded",
                    "content": {
                        "video_url": "https://example.com/out.mp4",
                        "last_frame_url": "https://example.com/last.png",
                    },
                }
            },
            "req-status",
        )


def test_client_submit_and_status_parsing():
    ark = FakeArk()
    client = SeedanceClient(
        client=ark,
        submit_endpoint="/submit",
        status_endpoint_template="/tasks/{task_id}",
    )
    submitted = client.submit(
        VideoGenerateRequest(
            model="m",
            prompt="p",
            ratio="16:9",
            duration=5,
            resolution="720p",
            reference_uris=["asset://asset-1"],
        )
    )
    status = client.status(submitted.task_id)

    assert submitted.task_id == "task-123"
    assert ark.payload["content"][1]["video_url"]["url"] == "asset://asset-1"
    assert status.status == "succeeded"
    assert status.file_url == "https://example.com/out.mp4"

