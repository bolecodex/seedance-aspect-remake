"""Pipeline operations used by the CLI commands."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, List, Optional

import typer

from seedance_aspect.ark import ArkClient
from seedance_aspect.ark_assets import ArkAssetsClient
from seedance_aspect.assets import load_asset_map
from seedance_aspect.config import AppConfig, ArkAssetsConfig
from seedance_aspect.errors import ConfigError, ManifestError, RequestError, SeedanceAspectError
from seedance_aspect.ffmpeg import (
    align_generated_segment,
    concat_videos,
    detect_scene_cuts,
    download_file,
    extract_last_frame,
    extract_reference_segment,
    get_duration,
    mux_original_audio,
    probe_video,
)
from seedance_aspect.manifest import Manifest, MediaReference, SegmentEntry
from seedance_aspect.planning import (
    choose_target_ratio,
    plan_scene_segments,
    plan_segments,
    validate_continuity,
    validate_generation_duration_mode,
    validate_split_strategy,
)
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
            "参考原片音频判断说话人，口型必须和对白同步，未说话角色保持自然反应。"
        )
    return (
        "以 16:9 横屏比例重新构图，严格保持原视频的全部动作、表演、镜头运动和节奏不变，"
        "仅调整画面构图比例。利用横向空间扩展场景，主体保持视觉中心，保留原始叙事顺序。"
        "参考原片音频判断说话人，口型必须和对白同步，未说话角色保持自然反应。"
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


def _build_assets_client(config: AppConfig) -> ArkAssetsClient:
    return ArkAssetsClient(config.require_assets())


def split_job(
    *,
    config: AppConfig,
    video: Path,
    output: Path,
    target: str,
    segment_seconds: int,
    prompt: str,
    asset_uris: List[str],
    asset_map_path: Optional[Path] = None,
    split_strategy: str = "scene",
    scene_threshold: float = 0.28,
    continuity: str = "always",
    reference_audio: bool = True,
    generation_duration_mode: str = "auto",
    alignment_mode: str = "trim-pad",
    no_upload: bool = False,
    auto_asset_ingest: bool = False,
    asset_group_id: str = "",
    asset_group_name: str = "",
    asset_project_name: str = "",
    keep_audio: bool = True,
    echo: Callable[[str], None] = typer.echo,
) -> Path:
    if not video.exists():
        raise ConfigError(f"输入视频不存在：{video}")

    info = probe_video(video)
    target_ratio = choose_target_ratio(info.width, info.height, target)
    split_strategy = validate_split_strategy(split_strategy)
    continuity = validate_continuity(continuity)
    generation_duration_mode = validate_generation_duration_mode(generation_duration_mode)
    if alignment_mode not in {"trim-pad", "speed"}:
        raise ConfigError("alignment-mode 仅支持 trim-pad、speed。")
    scene_cuts: List[float] = []
    if split_strategy == "scene":
        scene_cuts = detect_scene_cuts(video, threshold=scene_threshold)
        plans = plan_scene_segments(
            info.duration,
            scene_cuts,
            max_segment_seconds=segment_seconds,
            generation_duration_mode=generation_duration_mode,
        )
    else:
        plans = plan_segments(
            info.duration,
            max_segment_seconds=segment_seconds,
            generation_duration_mode=generation_duration_mode,
        )
    asset_map = load_asset_map(asset_map_path)
    if asset_uris and len(asset_uris) != len(plans):
        raise ConfigError(
            f"--asset-uris 数量必须与片段数量一致。当前 {len(asset_uris)} 个 URI，实际 {len(plans)} 个片段。"
        )
    extra_asset_indexes = [index for index in asset_map.segment_references if index >= len(plans)]
    if extra_asset_indexes:
        raise ConfigError(f"资产清单包含不存在的片段序号：{extra_asset_indexes}")
    source_reference_mode = "asset-only" if (asset_map.has_references or asset_uris or auto_asset_ingest) else "tos"

    output.mkdir(parents=True, exist_ok=True)
    references_dir = output / "references"
    raw_dir = output / "generated_raw"
    remade_dir = output / "remade"
    references_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    remade_dir.mkdir(parents=True, exist_ok=True)

    echo(f"源视频: {info.width}x{info.height}, {info.duration:.2f}s")
    echo(f"目标比例: {target_ratio}, 片段数: {len(plans)}")
    if split_strategy == "scene":
        echo(f"场景切分: threshold={scene_threshold}, 检测到 {len(scene_cuts)} 个候选切点")
    if source_reference_mode == "asset-only":
        if auto_asset_ingest:
            echo("参考素材: 将先把本地时序片段录入 Ark 私域素材库，再使用 asset:// 生成。")
        else:
            echo("参考素材: 使用 asset:// 私域素材，不上传原始真人视频片段。")
    if reference_audio and info.has_audio:
        echo("参考片段: 保留原音频作为口型/说话人参考，最终仍合回原音轨。")

    entries: List[SegmentEntry] = []
    for plan in plans:
        reference_path = references_dir / f"{plan.index:03d}.mp4"
        extract_reference_segment(video, reference_path, plan, include_audio=reference_audio)
        reference_uri: Optional[str] = None
        if asset_uris:
            reference_uri = asset_uris[plan.index]
        else:
            if source_reference_mode == "asset-only":
                echo(f"[{plan.index:03d}] 已生成本地时序片段；原始真人视频不会上传。")
            else:
                echo(f"[{plan.index:03d}] 已生成本地参考片段，尚未上传。")
        references = asset_map.references_for(plan.index)

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
                references=references,
                continuity_group=plan.continuity_group,
                continuity_from_previous=plan.continuity_from_previous,
                cut_reason=plan.cut_reason,
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
        source_reference_mode=source_reference_mode,
        split_strategy=split_strategy,
        scene_threshold=scene_threshold,
        continuity=continuity,
        reference_audio=reference_audio,
        generation_duration_mode=generation_duration_mode,
        alignment_mode=alignment_mode,
        asset_map_path=str(asset_map.path) if asset_map.path else None,
        asset_group_id=asset_group_id or config.asset_group_id or None,
        asset_project_name=asset_project_name or config.asset_project_name,
        auto_asset_ingest=auto_asset_ingest,
        segments=entries,
    )
    manifest_path = output / "manifest.json"
    manifest.save(manifest_path)
    echo(f"Manifest 已保存: {manifest_path}")
    if auto_asset_ingest:
        ingest_assets_job(
            config=config,
            manifest_path=manifest_path,
            group_id=asset_group_id,
            group_name=asset_group_name,
            project_name=asset_project_name,
            force=False,
            echo=echo,
        )
    elif not no_upload and source_reference_mode == "tos":
        upload_job(config=config, manifest_path=manifest_path, force=False, echo=echo)
    return manifest_path


def _segment_asset_reference(segment: SegmentEntry) -> Optional[MediaReference]:
    uri = segment.asset_uri or (f"asset://{segment.asset_id}" if segment.asset_id else None)
    if not uri:
        return None
    return MediaReference(
        uri=uri,
        media_type="video",
        role="reference_video",
        label=f"片段 {segment.index:03d} 授权视频素材",
    )


def _upsert_segment_asset_reference(segment: SegmentEntry) -> None:
    reference = _segment_asset_reference(segment)
    if not reference:
        return
    segment.references = [
        item for item in segment.references if not (item.uri == reference.uri and item.role == reference.role)
    ]
    segment.references.append(reference)
    segment.reference_uri = reference.uri


def ingest_assets_job(
    *,
    config: AppConfig,
    manifest_path: Path,
    group_id: str = "",
    group_name: str = "",
    project_name: str = "",
    force: bool = False,
    echo: Callable[[str], None] = typer.echo,
) -> None:
    manifest = Manifest.load(manifest_path)
    job_dir = manifest_path.parent
    tos_config = config.require_tos()
    assets_config = config.require_assets()
    target_project = project_name or manifest.asset_project_name or assets_config.project_name
    target_group_id = group_id or manifest.asset_group_id or assets_config.group_id
    target_group_name = (
        group_name
        or assets_config.group_name
        or f"seedance-aspect-{Path(manifest.source).stem}"[:64]
    )
    target_description = (
        assets_config.group_description
        or f"seedance-aspect 自动录入：{Path(manifest.source).name}"[:300]
    )
    client = _build_assets_client(config)

    if not manifest.segments:
        raise ManifestError("manifest 没有可录入的片段。")

    try:
        echo(f"准备 Ark 私域素材组: project={target_project}, name={target_group_name}")
        target_group_id = client.ensure_asset_group(
            group_id=target_group_id or "",
            group_name=target_group_name,
            description=target_description,
            project_name=target_project,
        )
        manifest.asset_group_id = target_group_id
        manifest.asset_project_name = target_project
        manifest.auto_asset_ingest = True
        manifest.source_reference_mode = "asset-only"
        manifest.save(manifest_path)
        echo(f"素材组就绪: {target_group_id}")

        for segment in _ordered_segments(manifest):
            if (
                not force
                and segment.asset_id
                and (segment.asset_status or "").lower() == "active"
            ):
                segment.asset_uri = segment.asset_uri or f"asset://{segment.asset_id}"
                _upsert_segment_asset_reference(segment)
                manifest.save(manifest_path)
                echo(f"[{segment.index:03d}] 已有 Active 素材: {segment.asset_uri}")
                continue

            local_reference = job_dir / segment.reference_path
            if not local_reference.exists():
                raise ManifestError(f"参考片段不存在：{local_reference}")

            echo(f"[{segment.index:03d}] 上传片段到 TOS 用于素材入库: {local_reference}")
            source_url = upload_file(local_reference, tos_config, prefix="seedance-aspect/assets/")
            segment.asset_source_url = source_url
            segment.asset_status = "Uploading"
            segment.asset_error = None
            manifest.save(manifest_path)

            asset_name = f"{Path(manifest.source).stem}-{segment.index:03d}"[:64]
            asset_id = client.create_asset(
                group_id=target_group_id,
                url=source_url,
                asset_type="Video",
                name=asset_name,
                project_name=target_project,
            )
            segment.asset_id = asset_id
            segment.asset_uri = f"asset://{asset_id}"
            segment.asset_status = "Processing"
            segment.asset_error = None
            manifest.save(manifest_path)
            echo(f"[{segment.index:03d}] 已创建素材: {segment.asset_uri}，等待 Active")

            result = client.wait_asset_active(
                asset_id,
                project_name=target_project,
                interval_s=assets_config.poll_interval_s,
                max_wait_s=assets_config.poll_max_wait_s,
                on_update=lambda raw, status, idx=segment.index: echo(f"  [{idx:03d}] 素材状态: {status}"),
            )
            segment.asset_status = result.status
            if result.status.lower() != "active":
                segment.asset_error = result.error_message or "素材入库失败。"
                manifest.save(manifest_path)
                raise RequestError(
                    f"片段 {segment.index:03d} 素材未变为 Active：{segment.asset_error}"
                )
            _upsert_segment_asset_reference(segment)
            segment.asset_error = None
            manifest.save(manifest_path)
            echo(f"[{segment.index:03d}] 素材 Active，可用于 Seedance: {segment.asset_uri}")
    finally:
        client.close()


def upload_job(
    *,
    config: AppConfig,
    manifest_path: Path,
    force: bool = False,
    echo: Callable[[str], None] = typer.echo,
) -> None:
    manifest = Manifest.load(manifest_path)
    job_dir = manifest_path.parent
    if manifest.source_reference_mode != "tos":
        echo("manifest 使用 asset-only 参考模式，无需上传原始视频片段。")
        return
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
    manifest: Manifest,
    job_dir: Path,
    segment: SegmentEntry,
    echo: Callable[[str], None],
) -> str:
    if segment.reference_uri:
        return segment.reference_uri
    if manifest.source_reference_mode == "asset-only":
        if segment.references:
            return ""
        raise ManifestError(
            f"片段 {segment.index:03d} 没有可用的 asset:// 私域素材。请在 asset-map 中补充该片段或全局素材。"
        )
    raise ManifestError(
        f"片段 {segment.index:03d} 尚未上传 TOS。请先运行：seedance-aspect upload {job_dir / 'manifest.json'}"
    )


def _ordered_segments(manifest: Manifest) -> List[SegmentEntry]:
    return sorted(manifest.segments, key=lambda item: item.index)


def _previous_segment(manifest: Manifest, segment: SegmentEntry) -> Optional[SegmentEntry]:
    ordered = _ordered_segments(manifest)
    for index, item in enumerate(ordered):
        if item.index == segment.index and index > 0:
            return ordered[index - 1]
    return None


def _next_segment(manifest: Manifest, segment: SegmentEntry) -> Optional[SegmentEntry]:
    ordered = _ordered_segments(manifest)
    for index, item in enumerate(ordered):
        if item.index == segment.index and index + 1 < len(ordered):
            return ordered[index + 1]
    return None


def _should_link_pair(manifest: Manifest, previous: SegmentEntry, current: SegmentEntry) -> bool:
    if manifest.continuity == "off":
        return False
    if manifest.continuity == "always":
        return True
    return current.continuity_from_previous or current.continuity_group == previous.continuity_group


def _build_request_references(
    manifest: Manifest,
    segment: SegmentEntry,
    *,
    tail_role: str = "first_frame",
) -> List[MediaReference]:
    references: List[MediaReference] = []
    if segment.first_frame_uri:
        references.append(
            MediaReference(
                uri=segment.first_frame_uri,
                media_type="image",
                role=tail_role,
                label="上一段最终尾帧",
            )
        )
    references.extend(segment.references)
    return references


def _ensure_first_frame_uri(
    *,
    config: AppConfig,
    manifest: Manifest,
    manifest_path: Path,
    segment: SegmentEntry,
    echo: Callable[[str], None],
) -> Optional[str]:
    previous = _previous_segment(manifest, segment)
    if previous is None or not _should_link_pair(manifest, previous, segment):
        return None
    if previous.status != "succeeded" or not previous.remade_path:
        raise ManifestError(f"片段 {segment.index:03d} 需要上一段尾帧，但上一段尚未成功。")
    uri = _ensure_tail_frame_uri(
        config=config,
        manifest=manifest,
        manifest_path=manifest_path,
        segment=previous,
        echo=echo,
    )
    segment.first_frame_uri = uri
    manifest.save(manifest_path)
    return uri


def _ensure_tail_frame_uri(
    *,
    config: AppConfig,
    manifest: Manifest,
    manifest_path: Path,
    segment: SegmentEntry,
    echo: Callable[[str], None],
) -> str:
    try:
        return _ensure_final_tail_frame_uri(
            config=config,
            manifest=manifest,
            manifest_path=manifest_path,
            segment=segment,
            echo=echo,
        )
    except Exception as exc:
        if segment.api_last_frame_url:
            echo(
                f"[{segment.index:03d}] 最终尾帧不可用，改用 Seedance 返回尾帧: "
                f"{_display_uri(segment.api_last_frame_url)}"
            )
            return segment.api_last_frame_url
        message = exc.message if isinstance(exc, SeedanceAspectError) else str(exc)
        raise ManifestError(
            f"片段 {segment.index:03d} 无法准备尾帧：{message}；Seedance 也未返回 last_frame_url。"
        ) from exc


def _ensure_tail_image_asset_uri(
    *,
    config: AppConfig,
    manifest: Manifest,
    manifest_path: Path,
    segment: SegmentEntry,
    echo: Callable[[str], None],
) -> str:
    if segment.final_last_frame_asset_uri and (segment.final_last_frame_asset_status or "").lower() == "active":
        return segment.final_last_frame_asset_uri

    assets_config = config.require_assets()
    project_name = manifest.asset_project_name or assets_config.project_name
    client = _build_assets_client(config)
    if segment.final_last_frame_asset_id:
        segment.final_last_frame_asset_uri = segment.final_last_frame_asset_uri or f"asset://{segment.final_last_frame_asset_id}"
        segment.final_last_frame_asset_error = None
        manifest.save(manifest_path)
        echo(f"[{segment.index:03d}] 继续等待已有尾帧图片素材: {segment.final_last_frame_asset_uri}")
        try:
            return _wait_tail_image_asset_active(
                client=client,
                assets_config=assets_config,
                project_name=project_name,
                manifest=manifest,
                manifest_path=manifest_path,
                segment=segment,
                echo=echo,
            )
        finally:
            client.close()

    source_url = _ensure_tail_frame_uri(
        config=config,
        manifest=manifest,
        manifest_path=manifest_path,
        segment=segment,
        echo=echo,
    )
    if source_url.startswith("asset://"):
        return source_url

    assets_config = config.require_assets()
    group_id = manifest.asset_group_id or assets_config.group_id
    if not group_id:
        raise ManifestError("尾帧图片入库需要 manifest.asset_group_id 或 ARK_ASSET_GROUP_ID。")
    try:
        asset_name = f"{Path(manifest.source).stem}-tail-{segment.index:03d}"[:64]
        asset_id = client.create_asset(
            group_id=group_id,
            url=source_url,
            asset_type="Image",
            name=asset_name,
            project_name=project_name,
        )
        segment.final_last_frame_asset_id = asset_id
        segment.final_last_frame_asset_uri = f"asset://{asset_id}"
        segment.final_last_frame_asset_status = "Processing"
        segment.final_last_frame_asset_error = None
        manifest.save(manifest_path)
        echo(f"[{segment.index:03d}] 已创建尾帧图片素材: {segment.final_last_frame_asset_uri}，等待 Active")
        return _wait_tail_image_asset_active(
            client=client,
            assets_config=assets_config,
            project_name=project_name,
            manifest=manifest,
            manifest_path=manifest_path,
            segment=segment,
            echo=echo,
        )
    finally:
        client.close()


def _wait_tail_image_asset_active(
    *,
    client: ArkAssetsClient,
    assets_config: ArkAssetsConfig,
    project_name: str,
    manifest: Manifest,
    manifest_path: Path,
    segment: SegmentEntry,
    echo: Callable[[str], None],
) -> str:
    if not segment.final_last_frame_asset_id:
        raise ManifestError(f"片段 {segment.index:03d} 没有可等待的尾帧图片素材。")
    result = client.wait_asset_active(
        segment.final_last_frame_asset_id,
        project_name=project_name,
        interval_s=assets_config.poll_interval_s,
        max_wait_s=assets_config.poll_max_wait_s,
        on_update=lambda raw, status: echo(f"  [{segment.index:03d}] 尾帧图片素材状态: {status}"),
    )
    segment.final_last_frame_asset_status = result.status
    segment.final_last_frame_asset_uri = segment.final_last_frame_asset_uri or f"asset://{segment.final_last_frame_asset_id}"
    if result.status.lower() != "active":
        segment.final_last_frame_asset_error = result.error_message or "尾帧图片素材入库失败。"
        manifest.save(manifest_path)
        raise RequestError(f"片段 {segment.index:03d} 尾帧图片素材未变为 Active：{segment.final_last_frame_asset_error}")
    segment.final_last_frame_asset_error = None
    manifest.save(manifest_path)
    echo(f"[{segment.index:03d}] 尾帧图片素材 Active: {segment.final_last_frame_asset_uri}")
    return segment.final_last_frame_asset_uri or f"asset://{segment.final_last_frame_asset_id}"


def _copy_tail_image_asset_state(source: SegmentEntry, target: SegmentEntry) -> None:
    target.final_last_frame_path = source.final_last_frame_path
    target.final_last_frame_uri = source.final_last_frame_uri
    target.final_last_frame_asset_id = source.final_last_frame_asset_id
    target.final_last_frame_asset_uri = source.final_last_frame_asset_uri
    target.final_last_frame_asset_status = source.final_last_frame_asset_status
    target.final_last_frame_asset_error = source.final_last_frame_asset_error


def _ensure_final_tail_frame_uri(
    *,
    config: AppConfig,
    manifest: Manifest,
    manifest_path: Path,
    segment: SegmentEntry,
    echo: Callable[[str], None],
) -> str:
    if segment.final_last_frame_uri:
        return segment.final_last_frame_uri
    if not segment.remade_path:
        raise ManifestError(f"片段 {segment.index:03d} 没有可抽帧的重制视频。")
    tos_config = config.require_tos()
    job_dir = manifest_path.parent
    frame_path = job_dir / "tail_frames" / f"{segment.index:03d}.png"
    extract_last_frame(job_dir / segment.remade_path, frame_path)
    uri = upload_file(frame_path, tos_config, prefix="seedance-aspect/frames/")
    segment.final_last_frame_path = str(frame_path.relative_to(job_dir))
    segment.final_last_frame_uri = uri
    manifest.save(manifest_path)
    echo(f"[{segment.index:03d}] 已保存最终尾帧: {_display_uri(uri)}")
    return uri


def _prepare_tail_for_next(
    *,
    config: AppConfig,
    manifest: Manifest,
    manifest_path: Path,
    segment: SegmentEntry,
    echo: Callable[[str], None],
) -> None:
    next_segment = _next_segment(manifest, segment)
    if next_segment and _should_link_pair(manifest, segment, next_segment):
        _ensure_tail_frame_uri(
            config=config,
            manifest=manifest,
            manifest_path=manifest_path,
            segment=segment,
            echo=echo,
        )


def _explicit_generation_duration(segment: SegmentEntry) -> int:
    return max(4, min(15, int(math.ceil(segment.duration))))


def _is_short_output(segment: SegmentEntry, generated_duration: float) -> bool:
    allowed_gap = max(0.75, segment.duration * 0.08)
    return generated_duration < segment.duration - allowed_gap


def _is_first_frame_reference_mix_error(exc: SeedanceAspectError) -> bool:
    return "first/last frame content cannot be mixed with reference media content" in exc.message


def _submit_request_with_tail_fallback(
    *,
    config: AppConfig,
    manifest: Manifest,
    client: SeedanceClient,
    request: VideoGenerateRequest,
    segment: SegmentEntry,
    manifest_path: Path,
    echo: Callable[[str], None],
) -> object:
    try:
        return client.submit(request)
    except RequestError as exc:
        if not segment.first_frame_uri or not _is_first_frame_reference_mix_error(exc):
            raise
        echo(
            f"[{segment.index:03d}] Seedance 不允许 first_frame 与参考视频混用，"
            "改用上一段尾帧私域图片素材作为 reference_image。"
        )
        latest_manifest = Manifest.load(manifest_path)
        previous = _previous_segment(latest_manifest, segment)
        if previous is None:
            raise
        original_previous = _previous_segment(manifest, segment)
        if original_previous is not None:
            try:
                asset_uri = _ensure_tail_image_asset_uri(
                    config=config,
                    manifest=latest_manifest,
                    manifest_path=manifest_path,
                    segment=previous,
                    echo=echo,
                )
            except SeedanceAspectError:
                _copy_tail_image_asset_state(previous, original_previous)
                raise
            _copy_tail_image_asset_state(previous, original_previous)
        else:
            asset_uri = _ensure_tail_image_asset_uri(
                config=config,
                manifest=latest_manifest,
                manifest_path=manifest_path,
                segment=previous,
                echo=echo,
            )
        segment.first_frame_uri = asset_uri
        manifest_segment = next((item for item in latest_manifest.segments if item.index == segment.index), None)
        if manifest_segment:
            manifest_segment.first_frame_uri = asset_uri
            latest_manifest.save(manifest_path)
        request.references = _build_request_references(latest_manifest, segment, tail_role="reference_image")
        return client.submit(request)


def _submit_and_poll_segment(
    *,
    config: AppConfig,
    manifest: Manifest,
    manifest_path: Path,
    job_dir: Path,
    client: SeedanceClient,
    segment: SegmentEntry,
    target_model: str,
    target_resolution: str,
    prompt_override: str,
    echo: Callable[[str], None],
) -> object:
    first_frame_uri = _ensure_first_frame_uri(
        config=config,
        manifest=manifest,
        manifest_path=manifest_path,
        segment=segment,
        echo=echo,
    )
    if first_frame_uri:
        echo(f"使用上一段最终尾帧作为首帧: {_display_uri(first_frame_uri)}")
    reference_uri = _ensure_reference_uri(
        manifest=manifest, job_dir=job_dir, segment=segment, echo=echo
    )
    prompt = prompt_override.strip() or manifest.prompt
    references = _build_request_references(manifest, segment)
    reference_uris = (
        [reference_uri]
        if reference_uri and not any(reference.uri == reference_uri for reference in references)
        else []
    )
    if not references and not reference_uris:
        raise ManifestError(
            f"片段 {segment.index:03d} 没有参考素材。请上传 TOS 或在 asset-map 中配置 asset:// URI。"
        )
    request = VideoGenerateRequest(
        model=target_model,
        prompt=prompt,
        ratio=manifest.target_ratio,
        duration=segment.generation_duration,
        resolution=target_resolution,
        reference_uris=reference_uris,
        references=references,
        safety_identifier=config.safety_identifier,
        watermark=False,
        generate_audio=False,
        return_last_frame=manifest.continuity != "off",
    )
    submitted = _submit_request_with_tail_fallback(
        config=config,
        manifest=manifest,
        client=client,
        request=request,
        segment=segment,
        manifest_path=manifest_path,
        echo=echo,
    )
    segment.task_id = submitted.task_id
    segment.status = "running"
    segment.attempts += 1
    segment.error = None
    manifest.save(manifest_path)
    echo(f"已提交 task_id={submitted.task_id}")
    return poll_task(
        client.status,
        submitted.task_id,
        interval_s=config.poll_interval_s,
        max_wait_s=config.poll_max_wait_s,
        on_update=lambda resp, status: echo(f"  状态: {resp.status} -> {status}"),
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

    pending = sorted(manifest.pending_segments(), key=lambda item: item.index)
    if not pending:
        echo("没有待处理片段。")
        return

    for segment in pending:
        echo(f"\n── 片段 {segment.index:03d} / {len(manifest.segments):03d} ──")
        try:
            if segment.status == "failed":
                if segment.task_id and segment.error and "调用火山方舟失败" in segment.error:
                    echo(f"上次为网络错误，保留 task_id 继续轮询：{segment.task_id}")
                    segment.status = "running"
                    segment.error = None
                else:
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
                result = _submit_and_poll_segment(
                    config=config,
                    manifest=manifest,
                    manifest_path=manifest_path,
                    job_dir=job_dir,
                    client=client,
                    segment=segment,
                    target_model=target_model,
                    target_resolution=target_resolution,
                    prompt_override=prompt_override,
                    echo=echo,
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
            raw_duration = get_duration(raw_path)
            if segment.generation_duration == -1 and _is_short_output(segment, raw_duration):
                explicit_duration = _explicit_generation_duration(segment)
                echo(
                    f"[重试] 片段 {segment.index:03d} 返回 {raw_duration:.2f}s，"
                    f"短于目标 {segment.duration:.2f}s；改用 duration={explicit_duration} 重新生成，避免补静止帧。"
                )
                segment.generation_duration = explicit_duration
                segment.task_id = None
                segment.generated_url = None
                segment.remade_path = None
                segment.status = "pending"
                segment.error = None
                manifest.save(manifest_path)
                result = _submit_and_poll_segment(
                    config=config,
                    manifest=manifest,
                    manifest_path=manifest_path,
                    job_dir=job_dir,
                    client=client,
                    segment=segment,
                    target_model=target_model,
                    target_resolution=target_resolution,
                    prompt_override=prompt_override,
                    echo=echo,
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
                download_file(result.file_url, raw_path)
                raw_duration = get_duration(raw_path)
                if _is_short_output(segment, raw_duration):
                    raise ConfigError(
                        f"片段 {segment.index:03d} 重新生成后仍过短："
                        f"{raw_duration:.2f}s < {segment.duration:.2f}s，已停止以避免静止画面补帧。"
                    )
            align_generated_segment(raw_path, remade_path, segment.duration, mode=manifest.alignment_mode)
            segment.generated_url = result.file_url
            segment.api_last_frame_url = result.last_frame_url
            segment.remade_path = str(remade_path.relative_to(job_dir))
            segment.status = "succeeded"
            segment.error = None
            manifest.save(manifest_path)
            _prepare_tail_for_next(
                config=config,
                manifest=manifest,
                manifest_path=manifest_path,
                segment=segment,
                echo=echo,
            )
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
            segment.api_last_frame_url = result.last_frame_url
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
        f"切分: strategy={manifest.split_strategy}, continuity={manifest.continuity}, source_reference={manifest.source_reference_mode}",
        f"片段: total={total}, succeeded={succeeded}, running={running}, failed={failed}, pending={pending}",
    ]
    for segment in sorted(manifest.segments, key=lambda item: item.index):
        suffix = f" task_id={segment.task_id}" if segment.task_id else ""
        if segment.first_frame_uri:
            suffix += " first_frame=ready"
        if segment.asset_status:
            suffix += f" asset={segment.asset_status}"
        if segment.error:
            suffix += f" error={segment.error}"
        if segment.asset_error:
            suffix += f" asset_error={segment.asset_error}"
        lines.append(
            f"[{segment.index:03d}] {segment.status} group={segment.continuity_group} cut={segment.cut_reason}{suffix}"
        )
    return lines
