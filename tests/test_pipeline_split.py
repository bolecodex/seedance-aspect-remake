import json
from pathlib import Path

from seedance_aspect.config import AppConfig
from seedance_aspect.errors import NetworkError, RequestError
from seedance_aspect.ffmpeg import VideoInfo
from seedance_aspect.manifest import Manifest, MediaReference, SegmentEntry
from seedance_aspect.pipeline import ingest_assets_job, remake_job, split_job
from seedance_aspect.seedance import SubmitResult, TaskStatus


def test_split_job_uploads_and_writes_manifest(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "input.mp4"
    input_video.write_bytes(b"fake")
    job_dir = tmp_path / "job"

    monkeypatch.setattr(
        "seedance_aspect.pipeline.probe_video",
        lambda path: VideoInfo(duration=31.0, width=1920, height=1080, fps=24.0, has_audio=True),
    )

    def fake_extract(video, output_path, plan, *, include_audio=True):
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
        split_strategy="uniform",
        no_upload=False,
        keep_audio=True,
        echo=lambda text: None,
    )
    manifest = Manifest.load(manifest_path)

    assert manifest.target_ratio == "9:16"
    assert manifest.continuity == "always"
    assert len(manifest.segments) == 3
    assert manifest.segments[0].reference_uri == "https://tos.example.com/000.mp4"
    assert "主体居中" in manifest.prompt


def test_split_with_asset_map_uses_asset_only_mode(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "input.mp4"
    input_video.write_bytes(b"fake")
    job_dir = tmp_path / "job"
    asset_map = tmp_path / "assets.json"
    asset_map.write_text(
        json.dumps({"global_references": [{"uri": "asset://asset-actor", "media_type": "image"}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "seedance_aspect.pipeline.probe_video",
        lambda path: VideoInfo(duration=5.0, width=720, height=1280, fps=24.0, has_audio=True),
    )
    monkeypatch.setattr("seedance_aspect.pipeline.detect_scene_cuts", lambda path, threshold: [])

    def fake_extract(video, output_path, plan, *, include_audio=True):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"segment")
        return output_path

    monkeypatch.setattr("seedance_aspect.pipeline.extract_reference_segment", fake_extract)

    manifest_path = split_job(
        config=AppConfig(tos_access_key="ak", tos_secret_key="sk", tos_bucket="bucket"),
        video=input_video,
        output=job_dir,
        target="auto-opposite",
        segment_seconds=15,
        prompt="",
        asset_uris=[],
        asset_map_path=asset_map,
        no_upload=False,
        keep_audio=True,
        echo=lambda text: None,
    )
    manifest = Manifest.load(manifest_path)

    assert manifest.target_ratio == "16:9"
    assert manifest.source_reference_mode == "asset-only"
    assert manifest.asset_map_path == str(asset_map)
    assert manifest.segments[0].reference_uri is None
    assert manifest.segments[0].references[0].role == "reference_image"


def test_ingest_assets_job_creates_asset_and_updates_manifest(monkeypatch, tmp_path: Path):
    job_dir = tmp_path / "job"
    reference_dir = job_dir / "references"
    reference_dir.mkdir(parents=True)
    (reference_dir / "000.mp4").write_bytes(b"segment")
    manifest_path = job_dir / "manifest.json"
    manifest = Manifest(
        source=str(tmp_path / "input.mp4"),
        target_ratio="16:9",
        prompt="保持节奏",
        source_reference_mode="asset-only",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=5,
                reference_duration=5,
                generation_duration=5,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
            )
        ],
    )
    manifest.save(manifest_path)

    class FakeAssetsClient:
        def ensure_asset_group(self, *, group_id="", group_name="", description="", project_name=None):
            assert group_name == "demo-group"
            assert project_name == "default"
            return "group-1"

        def create_asset(self, *, group_id, url, asset_type, name="", project_name=None):
            assert group_id == "group-1"
            assert url == "https://tos.example.com/000.mp4"
            assert asset_type == "Video"
            return "Asset-1"

        def wait_asset_active(self, asset_id, **kwargs):
            return type("Result", (), {"status": "Active", "error_message": "", "raw": {"Status": "Active"}})()

        def close(self):
            pass

    monkeypatch.setattr("seedance_aspect.pipeline._build_assets_client", lambda config: FakeAssetsClient())
    monkeypatch.setattr(
        "seedance_aspect.pipeline.upload_file",
        lambda path, tos_config, prefix="": f"https://tos.example.com/{path.name}",
    )

    ingest_assets_job(
        config=AppConfig(tos_access_key="ak", tos_secret_key="sk", tos_bucket="bucket"),
        manifest_path=manifest_path,
        group_name="demo-group",
        echo=lambda text: None,
    )
    loaded = Manifest.load(manifest_path)
    segment = loaded.segments[0]

    assert loaded.asset_group_id == "group-1"
    assert loaded.auto_asset_ingest is True
    assert segment.asset_status == "Active"
    assert segment.asset_uri == "asset://Asset-1"
    assert segment.reference_uri == "asset://Asset-1"
    assert segment.references[0].role == "reference_video"


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
        lambda raw, out, duration, **kwargs: out.parent.mkdir(parents=True, exist_ok=True) or out.write_bytes(b"aligned") or out,
    )
    monkeypatch.setattr("seedance_aspect.pipeline.get_duration", lambda path: 5.0)

    remake_job(config=AppConfig(api_key="key"), manifest_path=manifest_path, echo=lambda text: None)
    loaded = Manifest.load(manifest_path)

    assert fake_client.submitted is True
    assert loaded.segments[0].task_id == "new-task"
    assert loaded.segments[0].status == "succeeded"


def test_remake_uses_final_tail_frame_for_internal_continuity(monkeypatch, tmp_path: Path):
    manifest_path = tmp_path / "job" / "manifest.json"
    manifest = Manifest(
        source=str(tmp_path / "input.mp4"),
        target_ratio="16:9",
        prompt="保持节奏",
        source_reference_mode="asset-only",
        continuity="scene-tail",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=15,
                reference_duration=15,
                generation_duration=15,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
                remade_path="remade/000.mp4",
                status="succeeded",
                continuity_group=0,
            ),
            SegmentEntry(
                index=1,
                start=15,
                duration=5,
                reference_duration=5,
                generation_duration=5,
                source_path="references/001.mp4",
                reference_path="references/001.mp4",
                references=[
                    MediaReference(
                        uri="asset://asset-actor",
                        media_type="image",
                        role="reference_image",
                    )
                ],
                continuity_group=0,
                continuity_from_previous=True,
            ),
        ],
    )
    manifest.save(manifest_path)

    requests = []

    class FakeClient:
        def submit(self, request):
            requests.append(request)
            return SubmitResult(task_id="task-1")

        def status(self, task_id):
            return TaskStatus(task_id=task_id, status="succeeded", file_url="https://example.com/out.mp4")

    monkeypatch.setattr("seedance_aspect.pipeline._build_client", lambda config: FakeClient())
    monkeypatch.setattr(
        "seedance_aspect.pipeline.poll_task",
        lambda fetcher, task_id, **kwargs: TaskStatus(
            task_id=task_id,
            status="succeeded",
            file_url="https://example.com/out.mp4",
            last_frame_url="https://example.com/api-tail.png",
        ),
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.extract_last_frame",
        lambda video, frame: frame.parent.mkdir(parents=True, exist_ok=True) or frame.write_bytes(b"png") or frame,
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.upload_file",
        lambda path, tos_config, prefix="": "https://tos.example.com/tail.png",
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.download_file",
        lambda url, path: path.parent.mkdir(parents=True, exist_ok=True) or path.write_bytes(b"raw") or path,
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.align_generated_segment",
        lambda raw, out, duration, **kwargs: out.parent.mkdir(parents=True, exist_ok=True) or out.write_bytes(b"aligned") or out,
    )
    monkeypatch.setattr("seedance_aspect.pipeline.get_duration", lambda path: 5.0)

    remake_job(
        config=AppConfig(api_key="key", tos_access_key="ak", tos_secret_key="sk", tos_bucket="bucket"),
        manifest_path=manifest_path,
        echo=lambda text: None,
    )
    loaded = Manifest.load(manifest_path)
    roles = [ref.role for ref in requests[0].references]

    assert roles == ["first_frame", "reference_image"]
    assert loaded.segments[0].final_last_frame_uri == "https://tos.example.com/tail.png"
    assert loaded.segments[1].first_frame_uri == "https://tos.example.com/tail.png"
    assert loaded.segments[1].api_last_frame_url == "https://example.com/api-tail.png"


def test_remake_does_not_link_tail_across_scene_cut(monkeypatch, tmp_path: Path):
    manifest_path = tmp_path / "job" / "manifest.json"
    manifest = Manifest(
        source=str(tmp_path / "input.mp4"),
        target_ratio="16:9",
        prompt="保持节奏",
        source_reference_mode="asset-only",
        continuity="scene-tail",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=10,
                reference_duration=10,
                generation_duration=10,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
                remade_path="remade/000.mp4",
                status="succeeded",
                continuity_group=0,
            ),
            SegmentEntry(
                index=1,
                start=10,
                duration=5,
                reference_duration=5,
                generation_duration=5,
                source_path="references/001.mp4",
                reference_path="references/001.mp4",
                references=[
                    MediaReference(uri="asset://asset-actor", media_type="image", role="reference_image")
                ],
                continuity_group=1,
                continuity_from_previous=False,
            ),
        ],
    )
    manifest.save(manifest_path)
    requests = []

    class FakeClient:
        def submit(self, request):
            requests.append(request)
            return SubmitResult(task_id="task-1")

    monkeypatch.setattr("seedance_aspect.pipeline._build_client", lambda config: FakeClient())
    monkeypatch.setattr(
        "seedance_aspect.pipeline.poll_task",
        lambda fetcher, task_id, **kwargs: TaskStatus(task_id=task_id, status="succeeded", file_url="url"),
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.download_file",
        lambda url, path: path.parent.mkdir(parents=True, exist_ok=True) or path.write_bytes(b"raw") or path,
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.align_generated_segment",
        lambda raw, out, duration, **kwargs: out.parent.mkdir(parents=True, exist_ok=True) or out.write_bytes(b"aligned") or out,
    )
    monkeypatch.setattr("seedance_aspect.pipeline.get_duration", lambda path: 5.0)

    remake_job(config=AppConfig(api_key="key"), manifest_path=manifest_path, echo=lambda text: None)

    assert [ref.role for ref in requests[0].references] == ["reference_image"]


def test_remake_links_tail_across_scene_cut_when_always(monkeypatch, tmp_path: Path):
    manifest_path = tmp_path / "job" / "manifest.json"
    manifest = Manifest(
        source=str(tmp_path / "input.mp4"),
        target_ratio="16:9",
        prompt="保持节奏",
        source_reference_mode="asset-only",
        continuity="always",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=10,
                reference_duration=10,
                generation_duration=10,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
                remade_path="remade/000.mp4",
                status="succeeded",
                continuity_group=0,
            ),
            SegmentEntry(
                index=1,
                start=10,
                duration=5,
                reference_duration=5,
                generation_duration=5,
                source_path="references/001.mp4",
                reference_path="references/001.mp4",
                references=[
                    MediaReference(uri="asset://asset-actor", media_type="image", role="reference_image")
                ],
                continuity_group=1,
                continuity_from_previous=False,
            ),
        ],
    )
    manifest.save(manifest_path)
    requests = []

    class FakeClient:
        def submit(self, request):
            requests.append(request)
            return SubmitResult(task_id="task-1")

    monkeypatch.setattr("seedance_aspect.pipeline._build_client", lambda config: FakeClient())
    monkeypatch.setattr(
        "seedance_aspect.pipeline.poll_task",
        lambda fetcher, task_id, **kwargs: TaskStatus(task_id=task_id, status="succeeded", file_url="url"),
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.extract_last_frame",
        lambda video, frame: frame.parent.mkdir(parents=True, exist_ok=True) or frame.write_bytes(b"png") or frame,
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.upload_file",
        lambda path, tos_config, prefix="": "https://tos.example.com/tail.png",
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.download_file",
        lambda url, path: path.parent.mkdir(parents=True, exist_ok=True) or path.write_bytes(b"raw") or path,
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.align_generated_segment",
        lambda raw, out, duration, **kwargs: out.parent.mkdir(parents=True, exist_ok=True) or out.write_bytes(b"aligned") or out,
    )
    monkeypatch.setattr("seedance_aspect.pipeline.get_duration", lambda path: 5.0)

    remake_job(
        config=AppConfig(api_key="key", tos_access_key="ak", tos_secret_key="sk", tos_bucket="bucket"),
        manifest_path=manifest_path,
        echo=lambda text: None,
    )
    loaded = Manifest.load(manifest_path)

    assert [ref.role for ref in requests[0].references] == ["first_frame", "reference_image"]
    assert loaded.segments[1].first_frame_uri == "https://tos.example.com/tail.png"


def test_remake_falls_back_to_api_tail_frame(monkeypatch, tmp_path: Path):
    manifest_path = tmp_path / "job" / "manifest.json"
    manifest = Manifest(
        source=str(tmp_path / "input.mp4"),
        target_ratio="16:9",
        prompt="保持节奏",
        source_reference_mode="asset-only",
        continuity="always",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=10,
                reference_duration=10,
                generation_duration=10,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
                remade_path="remade/000.mp4",
                status="succeeded",
                api_last_frame_url="https://example.com/api-tail.png",
            ),
            SegmentEntry(
                index=1,
                start=10,
                duration=5,
                reference_duration=5,
                generation_duration=5,
                source_path="references/001.mp4",
                reference_path="references/001.mp4",
                references=[
                    MediaReference(uri="asset://asset-actor", media_type="image", role="reference_image")
                ],
            ),
        ],
    )
    manifest.save(manifest_path)
    requests = []

    class FakeClient:
        def submit(self, request):
            requests.append(request)
            return SubmitResult(task_id="task-1")

    monkeypatch.setattr("seedance_aspect.pipeline._build_client", lambda config: FakeClient())
    monkeypatch.setattr(
        "seedance_aspect.pipeline.poll_task",
        lambda fetcher, task_id, **kwargs: TaskStatus(task_id=task_id, status="succeeded", file_url="url"),
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.extract_last_frame",
        lambda video, frame: (_ for _ in ()).throw(RuntimeError("cannot extract tail")),
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.download_file",
        lambda url, path: path.parent.mkdir(parents=True, exist_ok=True) or path.write_bytes(b"raw") or path,
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.align_generated_segment",
        lambda raw, out, duration, **kwargs: out.parent.mkdir(parents=True, exist_ok=True) or out.write_bytes(b"aligned") or out,
    )
    monkeypatch.setattr("seedance_aspect.pipeline.get_duration", lambda path: 5.0)

    remake_job(config=AppConfig(api_key="key"), manifest_path=manifest_path, echo=lambda text: None)
    loaded = Manifest.load(manifest_path)

    assert [ref.role for ref in requests[0].references] == ["first_frame", "reference_image"]
    assert requests[0].references[0].uri == "https://example.com/api-tail.png"
    assert loaded.segments[0].final_last_frame_uri is None
    assert loaded.segments[1].first_frame_uri == "https://example.com/api-tail.png"


def test_remake_uses_tail_image_asset_when_first_frame_mix_is_rejected(monkeypatch, tmp_path: Path):
    manifest_path = tmp_path / "job" / "manifest.json"
    manifest = Manifest(
        source=str(tmp_path / "input.mp4"),
        target_ratio="16:9",
        prompt="保持节奏",
        source_reference_mode="asset-only",
        continuity="always",
        asset_group_id="group-1",
        asset_project_name="zhonghui",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=10,
                reference_duration=10,
                generation_duration=10,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
                remade_path="remade/000.mp4",
                status="succeeded",
                final_last_frame_uri="https://tos.example.com/tail.png",
            ),
            SegmentEntry(
                index=1,
                start=10,
                duration=5,
                reference_duration=5,
                generation_duration=5,
                source_path="references/001.mp4",
                reference_path="references/001.mp4",
                references=[
                    MediaReference(uri="asset://asset-shot", media_type="video", role="reference_video")
                ],
            ),
        ],
    )
    manifest.save(manifest_path)
    requests = []

    class FakeClient:
        def submit(self, request):
            requests.append(list(request.references))
            if len(requests) == 1:
                raise RequestError("first/last frame content cannot be mixed with reference media content")
            return SubmitResult(task_id="task-1")

        def status(self, task_id):
            return TaskStatus(task_id=task_id, status="succeeded", file_url="url")

    class FakeAssetsClient:
        def create_asset(self, **kwargs):
            assert kwargs["asset_type"] == "Image"
            assert kwargs["url"] == "https://tos.example.com/tail.png"
            assert kwargs["project_name"] == "zhonghui"
            return "asset-tail"

        def wait_asset_active(self, asset_id, **kwargs):
            return type("Result", (), {"status": "Active", "error_message": ""})()

        def close(self):
            pass

    monkeypatch.setattr("seedance_aspect.pipeline._build_client", lambda config: FakeClient())
    monkeypatch.setattr("seedance_aspect.pipeline._build_assets_client", lambda config: FakeAssetsClient())
    monkeypatch.setattr(
        "seedance_aspect.pipeline.poll_task",
        lambda fetcher, task_id, **kwargs: TaskStatus(task_id=task_id, status="succeeded", file_url="url"),
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.download_file",
        lambda url, path: path.parent.mkdir(parents=True, exist_ok=True) or path.write_bytes(b"raw") or path,
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.align_generated_segment",
        lambda raw, out, duration, **kwargs: out.parent.mkdir(parents=True, exist_ok=True) or out.write_bytes(b"aligned") or out,
    )
    monkeypatch.setattr("seedance_aspect.pipeline.get_duration", lambda path: 5.0)

    remake_job(
        config=AppConfig(api_key="key", tos_access_key="ak", tos_secret_key="sk", tos_bucket="bucket"),
        manifest_path=manifest_path,
        echo=lambda text: None,
    )
    loaded = Manifest.load(manifest_path)

    assert [ref.role for ref in requests[0]] == ["first_frame", "reference_video"]
    assert [ref.role for ref in requests[1]] == ["reference_image", "reference_video"]
    assert requests[1][0].uri == "asset://asset-tail"
    assert loaded.segments[0].final_last_frame_asset_uri == "asset://asset-tail"
    assert loaded.segments[1].status == "succeeded"


def test_remake_resumes_existing_tail_image_asset_after_timeout(monkeypatch, tmp_path: Path):
    manifest_path = tmp_path / "job" / "manifest.json"
    manifest = Manifest(
        source=str(tmp_path / "input.mp4"),
        target_ratio="16:9",
        prompt="保持节奏",
        source_reference_mode="asset-only",
        continuity="always",
        asset_group_id="group-1",
        asset_project_name="zhonghui",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=10,
                reference_duration=10,
                generation_duration=10,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
                remade_path="remade/000.mp4",
                status="succeeded",
                final_last_frame_uri="https://tos.example.com/tail.png",
                final_last_frame_asset_id="asset-tail",
                final_last_frame_asset_uri="asset://asset-tail",
                final_last_frame_asset_status="Processing",
                final_last_frame_asset_error="调用 Ark Assets API 失败：[Errno 60] Operation timed out",
            ),
            SegmentEntry(
                index=1,
                start=10,
                duration=5,
                reference_duration=5,
                generation_duration=5,
                source_path="references/001.mp4",
                reference_path="references/001.mp4",
                references=[
                    MediaReference(uri="asset://asset-shot", media_type="video", role="reference_video")
                ],
            ),
        ],
    )
    manifest.save(manifest_path)
    requests = []

    class FakeClient:
        def submit(self, request):
            requests.append(list(request.references))
            if len(requests) == 1:
                raise RequestError("first/last frame content cannot be mixed with reference media content")
            return SubmitResult(task_id="task-1")

        def status(self, task_id):
            return TaskStatus(task_id=task_id, status="succeeded", file_url="url")

    class FakeAssetsClient:
        def create_asset(self, **kwargs):
            raise AssertionError("should reuse the already-created tail image asset")

        def wait_asset_active(self, asset_id, **kwargs):
            assert asset_id == "asset-tail"
            return type("Result", (), {"status": "Active", "error_message": ""})()

        def close(self):
            pass

    monkeypatch.setattr("seedance_aspect.pipeline._build_client", lambda config: FakeClient())
    monkeypatch.setattr("seedance_aspect.pipeline._build_assets_client", lambda config: FakeAssetsClient())
    monkeypatch.setattr(
        "seedance_aspect.pipeline.poll_task",
        lambda fetcher, task_id, **kwargs: TaskStatus(task_id=task_id, status="succeeded", file_url="url"),
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.download_file",
        lambda url, path: path.parent.mkdir(parents=True, exist_ok=True) or path.write_bytes(b"raw") or path,
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.align_generated_segment",
        lambda raw, out, duration, **kwargs: out.parent.mkdir(parents=True, exist_ok=True) or out.write_bytes(b"aligned") or out,
    )
    monkeypatch.setattr("seedance_aspect.pipeline.get_duration", lambda path: 5.0)

    remake_job(
        config=AppConfig(api_key="key", tos_access_key="ak", tos_secret_key="sk", tos_bucket="bucket"),
        manifest_path=manifest_path,
        echo=lambda text: None,
    )
    loaded = Manifest.load(manifest_path)

    assert [ref.role for ref in requests[1]] == ["reference_image", "reference_video"]
    assert requests[1][0].uri == "asset://asset-tail"
    assert loaded.segments[0].final_last_frame_asset_status == "Active"
    assert loaded.segments[0].final_last_frame_asset_error is None
    assert loaded.segments[1].status == "succeeded"


def test_remake_preserves_created_tail_image_asset_when_wait_fails(monkeypatch, tmp_path: Path):
    manifest_path = tmp_path / "job" / "manifest.json"
    manifest = Manifest(
        source=str(tmp_path / "input.mp4"),
        target_ratio="16:9",
        prompt="保持节奏",
        source_reference_mode="asset-only",
        continuity="always",
        asset_group_id="group-1",
        asset_project_name="zhonghui",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=10,
                reference_duration=10,
                generation_duration=10,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
                remade_path="remade/000.mp4",
                status="succeeded",
                final_last_frame_uri="https://tos.example.com/tail.png",
            ),
            SegmentEntry(
                index=1,
                start=10,
                duration=5,
                reference_duration=5,
                generation_duration=5,
                source_path="references/001.mp4",
                reference_path="references/001.mp4",
                references=[
                    MediaReference(uri="asset://asset-shot", media_type="video", role="reference_video")
                ],
            ),
        ],
    )
    manifest.save(manifest_path)

    class FakeClient:
        def submit(self, request):
            raise RequestError("first/last frame content cannot be mixed with reference media content")

    class FakeAssetsClient:
        def create_asset(self, **kwargs):
            return "asset-tail"

        def wait_asset_active(self, asset_id, **kwargs):
            raise NetworkError("调用 Ark Assets API 失败：[Errno 60] Operation timed out")

        def close(self):
            pass

    monkeypatch.setattr("seedance_aspect.pipeline._build_client", lambda config: FakeClient())
    monkeypatch.setattr("seedance_aspect.pipeline._build_assets_client", lambda config: FakeAssetsClient())

    remake_job(
        config=AppConfig(api_key="key", tos_access_key="ak", tos_secret_key="sk", tos_bucket="bucket"),
        manifest_path=manifest_path,
        echo=lambda text: None,
    )
    loaded = Manifest.load(manifest_path)

    assert loaded.segments[0].final_last_frame_asset_id == "asset-tail"
    assert loaded.segments[0].final_last_frame_asset_uri == "asset://asset-tail"
    assert loaded.segments[0].final_last_frame_asset_status == "Processing"
    assert loaded.segments[1].status == "failed"
    assert "Operation timed out" in (loaded.segments[1].error or "")


def test_remake_retries_auto_duration_when_output_is_too_short(monkeypatch, tmp_path: Path):
    manifest_path = tmp_path / "job" / "manifest.json"
    manifest = Manifest(
        source=str(tmp_path / "input.mp4"),
        target_ratio="16:9",
        prompt="保持节奏",
        generation_duration_mode="auto",
        alignment_mode="trim-pad",
        segments=[
            SegmentEntry(
                index=0,
                start=0,
                duration=14.32,
                reference_duration=14.32,
                generation_duration=-1,
                source_path="references/000.mp4",
                reference_path="references/000.mp4",
                reference_uri="asset://asset-1",
            )
        ],
    )
    manifest.save(manifest_path)
    submitted_durations = []

    class FakeClient:
        def submit(self, request):
            submitted_durations.append(request.duration)
            return SubmitResult(task_id=f"task-{len(submitted_durations)}")

        def status(self, task_id):
            return TaskStatus(task_id=task_id, status="running")

    monkeypatch.setattr("seedance_aspect.pipeline._build_client", lambda config: FakeClient())
    monkeypatch.setattr(
        "seedance_aspect.pipeline.poll_task",
        lambda fetcher, task_id, **kwargs: TaskStatus(
            task_id=task_id,
            status="succeeded",
            file_url=f"https://example.com/{task_id}.mp4",
        ),
    )
    monkeypatch.setattr(
        "seedance_aspect.pipeline.download_file",
        lambda url, path: path.parent.mkdir(parents=True, exist_ok=True) or path.write_bytes(url.encode()) or path,
    )
    durations = iter([8.04, 15.0])
    monkeypatch.setattr("seedance_aspect.pipeline.get_duration", lambda path: next(durations))
    monkeypatch.setattr(
        "seedance_aspect.pipeline.align_generated_segment",
        lambda raw, out, duration, **kwargs: out.parent.mkdir(parents=True, exist_ok=True) or out.write_bytes(b"aligned") or out,
    )

    remake_job(config=AppConfig(api_key="key"), manifest_path=manifest_path, echo=lambda text: None)
    loaded = Manifest.load(manifest_path)

    assert submitted_durations == [-1, 15]
    assert loaded.segments[0].generation_duration == 15
    assert loaded.segments[0].status == "succeeded"
