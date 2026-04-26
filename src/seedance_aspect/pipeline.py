"""Pipeline operations used by the CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

import typer

from seedance_aspect.ark import ArkClient
from seedance_aspect.config import AppConfig
from seedance_aspect.errors import ConfigError, ManifestError, SeedanceAspectError
from seedance_aspect.ffmpeg import (
    align_generated_segment,
    concat_videos,
    download_file,
    extract_reference_segment,
    mux_original_audio,
    probe_video,
)
from seedance_aspect.manifest import Manifest, SegmentEntry
from seedance_aspect.planning import choose_target_ratio, plan_segments
from seedance_aspect.seedance import (
    SeedanceClient,
    VideoGenerateRequest,
    normalize_status,
    poll_task,
)
from seedance_aspect.tos_upload import upload_file


def default_prompt(target_ratio: str) -> str:
    if target_ratio == "9:16":
        return (
            "以 9:16 竖屏比例重新构图，严格保持原视频的全部动作、表演、镜头运动和节奏不变，"
            "仅调整画面构图比例。主体保持稳定、自然居中，保留原始叙事顺序和剪辑节奏。"
        )
    return (
        "以 16:9 横屏比例重新构图，严格保持原视频的全部动作、表演、镜头运动和节奏不变，"
        "仅调整画面构图比例。利用横向空间扩展场景，主体保持视觉中心，保留原始叙事顺序。"
    )


def parse_asset_uris(raw: str) -> List[str]:
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _display_uri(uri: str) -> str:
    if uri.startswith("asset://"):
        return uri
    return uri.split("?", 1)[0]


def _compose_prompt(target_ratio: str, extra_prompt: str) -> str:
    prompt = default_prompt(target_ratio)
    if extra_prompt.strip():
        prompt = f"{prompt}\n{extra_prompt.strip()}"
    return prompt


def _build_client(config: AppConfig) -> SeedanceClient:
    return SeedanceClient(
        client=ArkClient(
            api_key=config.require_api_key(),
            base_url=config.base_url,
            timeout_s=config.request_timeout_s,
        ),
        submit_endpoint=config.video_submit_endpoint,
        status_endpoint_template=config.video_status_endpoint_template,
    )


def split_job(
    *,
    config: AppConfig,
    video: Path,
    output: Path,
    target: str,
    segment_seconds: int,
    prompt: str,
    asset_uris: List[str],
    no_upload: bool,
    keep_audio: bool,
    echo: Callable[[str], None] = typer.echo,
) -> Path:
    if not video.exists():
        raise ConfigError(f"输入视频不存在：{video}")

    info = probe_video(video)
    target_ratio = choose_target_ratio(info.width, info.height, target)
    plans = plan_segments(info.duration, max_segment_seconds=segment_seconds)
    if asset_uris and len(asset_uris) != len(plans):
        raise ConfigError(
            f"--asset-uris 数量必须与片段数量一致。当前 {len(asset_uris)} 个 URI，实际 {len(plans)} 个片段。"
        )

    output.mkdir(parents=True, exist_ok=True)
    references_dir = output / "references"
    raw_dir = output / "generated_raw"
    remade_dir = output / "remade"
    references_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    remade_dir.mkdir(parents=True, exist_ok=True)

    echo(f"源视频: {info.width}x{info.height}, {info.duration:.2f}s")
    echo(f"目标比例: {target_ratio}, 片段数: {len(plans)}")

    entries: List[SegmentEntry] = []
    for plan in plans:
        reference_path = references_dir / f"{plan.index:03d}.mp4"
        extract_reference_segment(video, reference_path, plan)
        reference_uri: Optional[str] = None
        if asset_uris:
            reference_uri = asset_uris[plan.index]
        else:
            echo(f"[{plan.index:03d}] 已生成本地参考片段，尚未上传。")

        entries.append(
            SegmentEntry(
                index=plan.index,
                start=round(plan.start, 3),
                duration=round(plan.duration, 3),
                reference_duration=round(plan.reference_duration, 3),
                generation_duration=plan.generation_duration,
                source_path=str(reference_path.relative_to(output)),
                reference_path=str(reference_path.relative_to(output)),
                reference_uri=reference_uri,
            )
        )

    manifest = Manifest(
        source=str(video.resolve()),
        target_ratio=target_ratio,
        prompt=_compose_prompt(target_ratio, prompt),
        model=config.model,
        resolution=config.resolution,
        segment_seconds=segment_seconds,
        keep_audio=keep_audio,
        segments=entries,
    )
    manifest_path = output / "manifest.json"
    manifest.save(manifest_path)
    echo(f"Manifest 已保存: {manifest_path}")
    if not no_upload and not asset_uris:
        upload_job(config=config, manifest_path=manifest_path, force=False, echo=echo)
    return manifest_path


def upload_job(
    *,
    config: AppConfig,
    manifest_path: Path,
    force: bool = False,
    echo: Callable[[str], None] = typer.echo,
) -> None:
    manifest = Manifest.load(manifest_path)
    job_dir = manifest_path.parent
    tos_config = config.require_tos()
    uploadable = [
        segment
        for segment in sorted(manifest.segments, key=lambda item: item.index)
        if not segment.reference_uri or (force and not segment.reference_uri.startswith("asset://"))
    ]
    if not uploadable:
        echo("所有片段都已有参考 URI，无需上传。")
        return

    echo(f"开始上传 TOS: {len(uploadable)} 个本地参考片段")
    for segment in uploadable:
        if segment.reference_uri and segment.reference_uri.startswith("asset://"):
            echo(f"[{segment.index:03d}] 使用授权素材: {segment.reference_uri}")
            continue
        local_reference = job_dir / segment.reference_path
        if not local_reference.exists():
            raise ManifestError(f"参考片段不存在：{local_reference}")
        echo(f"[{segment.index:03d}] 上传 TOS: {local_reference}")
        uri = upload_file(local_reference, tos_config)
        segment.reference_uri = uri
        manifest.save(manifest_path)
        echo(f"[{segment.index:03d}] 已上传 TOS: {_display_uri(uri)}")


def _face_policy_hint(message: str) -> str:
    lower = message.lower()
    if any(token in lower for token in ["face", "real person", "portrait", "人脸", "真人", "肖像"]):
        return (
            f"{message}\n"
            "提示：Seedance 2.0 对含真人人脸的参考图/视频有官方授权要求。"
            "请在火山方舟完成人像素材授权后，使用 asset://<asset_id> 写入 manifest 或通过 --asset-uris 传入。"
        )
    return message


def _ensure_reference_uri(
    *,
    config: AppConfig,
    job_dir: Path,
    segment: SegmentEntry,
    echo: Callable[[str], None],
) -> str:
    if segment.reference_uri:
        return segment.reference_uri
    raise ManifestError(
        f"片段 {segment.index:03d} 尚未上传 TOS。请先运行：seedance-aspect upload {job_dir / 'manifest.json'}"
    )


def remake_job(
    *,
    config: AppConfig,
    manifest_path: Path,
    prompt_override: str = "",
    model: str = "",
    resolution: str = "",
    continue_on_error: bool = True,
    echo: Callable[[str], None] = typer.echo,
) -> None:
    manifest = Manifest.load(manifest_path)
    job_dir = manifest_path.parent
    client = _build_client(config)
    target_model = model or manifest.model or config.model
    target_resolution = resolution or manifest.resolution or config.resolution

    pending = manifest.pending_segments()
    if not pending:
        echo("没有待处理片段。")
        return

    for segment in pending:
        echo(f"\n── 片段 {segment.index:03d} / {len(manifest.segments):03d} ──")
        try:
            if segment.status == "failed":
                segment.task_id = None
                segment.generated_url = None
                segment.remade_path = None
                if segment.reference_uri and not segment.reference_uri.startswith("asset://"):
                    segment.reference_uri = None

            if segment.task_id:
                echo(f"恢复轮询 task_id={segment.task_id}")
                result = poll_task(
                    client.status,
                    segment.task_id,
                    interval_s=config.poll_interval_s,
                    max_wait_s=config.poll_max_wait_s,
                    on_update=lambda resp, status: echo(f"  状态: {resp.status} -> {status}"),
                )
            else:
                reference_uri = _ensure_reference_uri(
                    config=config, job_dir=job_dir, segment=segment, echo=echo
                )
                prompt = prompt_override.strip() or manifest.prompt
                request = VideoGenerateRequest(
                    model=target_model,
                    prompt=prompt,
                    ratio=manifest.target_ratio,
                    duration=segment.generation_duration,
                    resolution=target_resolution,
                    reference_uris=[reference_uri],
                    safety_identifier=config.safety_identifier,
                    watermark=False,
                    generate_audio=False,
                )
                submitted = client.submit(request)
                segment.task_id = submitted.task_id
                segment.status = "running"
                segment.attempts += 1
                segment.error = None
                manifest.save(manifest_path)
                echo(f"已提交 task_id={submitted.task_id}")
                result = poll_task(
                    client.status,
                    submitted.task_id,
                    interval_s=config.poll_interval_s,
                    max_wait_s=config.poll_max_wait_s,
                    on_update=lambda resp, status: echo(f"  状态: {resp.status} -> {status}"),
                )

            normalized = normalize_status(result.status)
            if normalized != "succeeded" or not result.file_url:
                reason = _face_policy_hint(result.fail_reason or result.status)
                segment.status = "failed"
                segment.error = reason
                manifest.save(manifest_path)
                echo(f"[失败] {reason}")
                if not continue_on_error:
                    raise ConfigError(reason)
                continue

            raw_path = job_dir / "generated_raw" / f"{segment.index:03d}.mp4"
            remade_path = job_dir / "remade" / f"{segment.index:03d}.mp4"
            download_file(result.file_url, raw_path)
            align_generated_segment(raw_path, remade_path, segment.duration)
            segment.generated_url = result.file_url
            segment.remade_path = str(remade_path.relative_to(job_dir))
            segment.status = "succeeded"
            segment.error = None
            manifest.save(manifest_path)
            echo(f"[完成] {segment.remade_path}")
        except SeedanceAspectError as exc:
            message = _face_policy_hint(exc.message)
            segment.status = "failed"
            segment.error = message
            manifest.save(manifest_path)
            echo(f"[失败] {message}")
            if not continue_on_error:
                raise
        except Exception as exc:
            message = _face_policy_hint(str(exc))
            segment.status = "failed"
            segment.error = message
            manifest.save(manifest_path)
            echo(f"[失败] {message}")
            if not continue_on_error:
                raise ConfigError(message) from exc


def merge_job(
    *,
    manifest_path: Path,
    output: Optional[Path],
    keep_audio: Optional[bool],
    echo: Callable[[str], None] = typer.echo,
) -> Path:
    manifest = Manifest.load(manifest_path)
    job_dir = manifest_path.parent
    missing = [seg for seg in manifest.segments if seg.status != "succeeded" or not seg.remade_path]
    if missing:
        failed = ", ".join(f"{seg.index:03d}:{seg.status}" for seg in missing)
        raise ManifestError(f"仍有片段未成功，不能拼接：{failed}")

    video_paths = [job_dir / seg.remade_path for seg in sorted(manifest.segments, key=lambda item: item.index)]
    for path in video_paths:
        if not path.exists():
            raise ManifestError(f"重制片段不存在：{path}")

    out_path = output or (job_dir / "final.mp4")
    should_keep_audio = manifest.keep_audio if keep_audio is None else keep_audio
    if should_keep_audio:
        temp_video = out_path.with_name(out_path.stem + "_video_only" + out_path.suffix)
        concat_videos(video_paths, temp_video)
        mux_original_audio(temp_video, Path(manifest.source), out_path)
        temp_video.unlink(missing_ok=True)
    else:
        concat_videos(video_paths, out_path)
    echo(f"成片已生成: {out_path}")
    return out_path


def refresh_status(
    *,
    config: AppConfig,
    manifest_path: Path,
    echo: Callable[[str], None] = typer.echo,
) -> None:
    manifest = Manifest.load(manifest_path)
    client = _build_client(config)
    changed = False
    for segment in manifest.segments:
        if not segment.task_id:
            continue
        result = client.status(segment.task_id)
        normalized = normalize_status(result.status)
        if normalized == "succeeded" and result.file_url:
            segment.status = "succeeded" if segment.remade_path else "running"
            segment.generated_url = result.file_url
            segment.error = None
        elif normalized == "failed":
            segment.status = "failed"
            segment.error = _face_policy_hint(result.fail_reason or result.status)
        else:
            segment.status = "running"
        changed = True
    if changed:
        manifest.save(manifest_path)
        echo("已刷新远端任务状态。")


def summarize_status(manifest: Manifest) -> List[str]:
    total = len(manifest.segments)
    succeeded = len([seg for seg in manifest.segments if seg.status == "succeeded"])
    running = len([seg for seg in manifest.segments if seg.status == "running"])
    failed = len([seg for seg in manifest.segments if seg.status == "failed"])
    pending = total - succeeded - running - failed
    lines = [
        f"源视频: {manifest.source}",
        f"目标比例: {manifest.target_ratio}",
        f"片段: total={total}, succeeded={succeeded}, running={running}, failed={failed}, pending={pending}",
    ]
    for segment in sorted(manifest.segments, key=lambda item: item.index):
        suffix = f" task_id={segment.task_id}" if segment.task_id else ""
        if segment.error:
            suffix += f" error={segment.error}"
        lines.append(f"[{segment.index:03d}] {segment.status}{suffix}")
    return lines
