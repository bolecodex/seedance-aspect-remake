from pathlib import Path

from seedance_aspect.config import AppConfig
from seedance_aspect.ffmpeg import VideoInfo
from seedance_aspect.manifest import Manifest, SegmentEntry
from seedance_aspect.pipeline import remake_job, split_job
from seedance_aspect.seedance import SubmitResult, TaskStatus


def test_split_job_uploads_and_writes_manifest(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "input.mp4"
    input_video.write_bytes(b"fake")
    job_dir = tmp_path / "job"

    monkeypatch.setattr(
        "seedance_aspect.pipeline.probe_video",
        lambda path: VideoInfo(duration=31.0, width=1920, height=1080, fps=24.0, has_audio=True),
    )

    def fake_extract(video, output_path, plan):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"segment")
        return output_path

    monkeypatch.setattr("seedance_aspect.pipeline.extract_reference_segment", fake_extract)
    monkeypatch.setattr(
        "seedance_aspect.pipeline.upload_file",
        lambda path, tos_config: f"https://tos.example.com/{path.name}",
    )

    manifest_path = split_job(
        config=AppConfig(
            tos_access_key="ak",
            tos_secret_key="sk",
            tos_bucket="bucket",
        ),
        video=input_video,
        output=job_dir,
        target="auto-opposite",
        segment_seconds=15,
        prompt="主体居中",
        asset_uris=[],
        no_upload=False,
        keep_audio=True,
        echo=lambda text: None,
    )
    manifest = Manifest.load(manifest_path)

    assert manifest.target_ratio == "9:16"
    assert len(manifest.segments) == 3
    assert manifest.segments[0].reference_uri == "https://tos.example.com/000.mp4"
    assert "主体居中" in manifest.prompt


def test_remake_resubmits_failed_segment(monkeypatch, tmp_path: Path):
    manifest_path = tmp_path / "job" / "manifest.json"
    manifest = Manifest(
        source=str(tmp_path / "input.mp4"),
        target_ratio="9:16",
        prompt="保持节奏",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=5,
                reference_duration=5,
                generation_duration=5,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
                reference_uri="asset://asset-1",
                task_id="old-failed-task",
                status="failed",
                error="old error",
            )
        ],
    )
    manifest.save(manifest_path)

    class FakeClient:
        def __init__(self):
            self.submitted = False

        def submit(self, request):
            self.submitted = True
            return SubmitResult(task_id="new-task")

        def status(self, task_id):
            return TaskStatus(task_id=task_id, status="succeeded", file_url="https://example.com/out.mp4")

    fake_client = FakeClient()
    monkeypatch.setattr("seedance_aspect.pipeline._build_client", lambda config: fake_client)
    monkeypatch.setattr(
        "seedance_aspect.pipeline.poll_task",
        lambda fetcher, task_id, **kwargs: TaskStatus(
            task_id=task_id, status="succeeded", file_url="https://example.com/out.mp4"
        ),
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.download_file",
        lambda url, path: path.parent.mkdir(parents=True, exist_ok=True) or path.write_bytes(b"raw") or path,
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.align_generated_segment",
        lambda raw, out, duration: out.parent.mkdir(parents=True, exist_ok=True) or out.write_bytes(b"aligned") or out,
    )

    remake_job(config=AppConfig(api_key="key"), manifest_path=manifest_path, echo=lambda text: None)
    loaded = Manifest.load(manifest_path)

    assert fake_client.submitted is True
    assert loaded.segments[0].task_id == "new-task"
    assert loaded.segments[0].status == "succeeded"
