"""Typer CLI entry point."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from seedance_aspect import __version__
from seedance_aspect.config import load_config
from seedance_aspect.errors import SeedanceAspectError
from seedance_aspect.manifest import Manifest
from seedance_aspect.pipeline import (
    ingest_assets_job,
    merge_job,
    parse_asset_uris,
    refresh_status,
    remake_job,
    split_job,
    summarize_status,
    upload_job,
)

app = typer.Typer(
    add_completion=False,
    help=(
        "seedance-aspect — 使用 Seedance 2.0 做视频横竖屏转换\n\n"
        "长视频会自动拆分、上传 TOS、逐段生成、对齐时长、拼接，并默认合回原音轨。"
    ),
)


@app.callback()
def root(
    ctx: typer.Context,
    api_key: str = typer.Option("", "--api-key", help="临时指定 ARK_API_KEY。"),
    base_url: str = typer.Option("", "--base-url", help="临时指定火山方舟 Base URL。"),
    model: str = typer.Option("", "--model", help="临时指定 Seedance 模型。"),
    resolution: str = typer.Option("", "--resolution", help="临时指定生成分辨率，例如 720p。"),
    output_json: bool = typer.Option(False, "--json", help="错误信息使用 JSON 输出。"),
) -> None:
    ctx.obj = load_config(
        {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "resolution": resolution,
        }
    )


@app.command()
def version() -> None:
    """显示版本号。"""
    typer.echo(f"seedance-aspect {__version__}")


@app.command()
def split(
    ctx: typer.Context,
    video: Path = typer.Argument(..., help="输入视频路径。"),
    output: Path = typer.Option(..., "-o", "--output", help="任务输出目录。"),
    target: str = typer.Option("auto-opposite", "--target", help="9:16、16:9 或 auto-opposite。"),
    segment_seconds: int = typer.Option(15, "--segment-seconds", "-s", help="每段最大秒数，范围 2-15。"),
    prompt: str = typer.Option("", "--prompt", help="追加提示词。"),
    asset_uris: str = typer.Option("", "--asset-uris", help="逗号分隔的 asset:// URI，数量需等于片段数。"),
    asset_map: Optional[Path] = typer.Option(None, "--asset-map", help="私域人像/视频素材清单 JSON。"),
    split_strategy: str = typer.Option("scene", "--split-strategy", help="scene 或 uniform。"),
    scene_threshold: float = typer.Option(0.28, "--scene-threshold", help="FFmpeg scene 检测阈值。"),
    continuity: str = typer.Option("always", "--continuity", help="always、scene-tail 或 off。"),
    reference_audio: bool = typer.Option(True, "--reference-audio/--no-reference-audio", help="参考片段保留原音频，用于口型和说话人判断。"),
    generation_duration_mode: str = typer.Option("auto", "--generation-duration-mode", help="auto 使用 Seedance 自动时长；ceil 使用整数秒。"),
    alignment_mode: str = typer.Option("trim-pad", "--alignment-mode", help="trim-pad 不变速裁剪/补尾；speed 整体变速对齐。"),
    no_upload: bool = typer.Option(False, "--no-upload", help="只生成本地片段和 manifest，不上传 TOS。"),
    auto_asset_ingest: bool = typer.Option(False, "--auto-asset-ingest", help="拆分后自动上传 TOS 并录入 Ark 私域素材库。"),
    asset_group_id: str = typer.Option("", "--asset-group-id", help="使用已有 Ark 素材组 ID。"),
    asset_group_name: str = typer.Option("", "--asset-group-name", help="自动创建/复用的 Ark 素材组名称。"),
    asset_project_name: str = typer.Option("", "--asset-project-name", help="Ark 资源所属 ProjectName，默认 default。"),
    keep_audio: bool = typer.Option(True, "--keep-audio/--no-keep-audio", help="merge 时默认合回原音轨。"),
) -> None:
    """先完成本地拆分处理，再按需批量上传 TOS，并生成 manifest.json。"""
    split_job(
        config=ctx.obj,
        video=video,
        output=output,
        target=target,
        segment_seconds=segment_seconds,
        prompt=prompt,
        asset_uris=parse_asset_uris(asset_uris),
        asset_map_path=asset_map,
        split_strategy=split_strategy,
        scene_threshold=scene_threshold,
        continuity=continuity,
        reference_audio=reference_audio,
        generation_duration_mode=generation_duration_mode,
        alignment_mode=alignment_mode,
        no_upload=no_upload,
        auto_asset_ingest=auto_asset_ingest,
        asset_group_id=asset_group_id,
        asset_group_name=asset_group_name,
        asset_project_name=asset_project_name,
        keep_audio=keep_audio,
    )


@app.command()
def upload(
    ctx: typer.Context,
    manifest_path: Path = typer.Argument(..., help="manifest.json 路径。"),
    force: bool = typer.Option(False, "--force", help="重新上传已有 TOS URL 的片段；asset:// 不会被覆盖。"),
) -> None:
    """批量上传 manifest 中尚未上传的本地参考片段。"""
    upload_job(config=ctx.obj, manifest_path=manifest_path, force=force)


@app.command("ingest-assets")
def ingest_assets(
    ctx: typer.Context,
    manifest_path: Path = typer.Argument(..., help="manifest.json 路径。"),
    group_id: str = typer.Option("", "--asset-group-id", help="使用已有 Ark 素材组 ID。"),
    group_name: str = typer.Option("", "--asset-group-name", help="自动创建/复用的 Ark 素材组名称。"),
    project_name: str = typer.Option("", "--asset-project-name", help="Ark 资源所属 ProjectName，默认 default。"),
    force: bool = typer.Option(False, "--force", help="重新上传并创建素材，覆盖已有 Active 资产引用。"),
) -> None:
    """把本地参考片段上传 TOS 后录入 Ark 私域素材库，并写回 asset:// 引用。"""
    ingest_assets_job(
        config=ctx.obj,
        manifest_path=manifest_path,
        group_id=group_id,
        group_name=group_name,
        project_name=project_name,
        force=force,
    )


@app.command()
def remake(
    ctx: typer.Context,
    manifest_path: Path = typer.Argument(..., help="manifest.json 路径。"),
    prompt: str = typer.Option("", "--prompt", help="覆盖 manifest 中的提示词。"),
    model: str = typer.Option("", "--model", help="临时覆盖 Seedance 模型。"),
    resolution: str = typer.Option("", "--resolution", help="临时覆盖生成分辨率。"),
    stop_on_error: bool = typer.Option(False, "--stop-on-error", help="任一片段失败后停止。"),
) -> None:
    """提交或恢复 Seedance 任务，并下载对齐后的片段；要求片段已先上传。"""
    remake_job(
        config=ctx.obj,
        manifest_path=manifest_path,
        prompt_override=prompt,
        model=model,
        resolution=resolution,
        continue_on_error=not stop_on_error,
    )


@app.command()
def merge(
    manifest_path: Path = typer.Argument(..., help="manifest.json 路径。"),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="输出视频路径，默认 job/final.mp4。"),
    keep_audio: Optional[bool] = typer.Option(None, "--keep-audio/--no-keep-audio", help="是否合回原音轨。"),
) -> None:
    """拼接所有成功片段，并按需合回原音轨。"""
    merge_job(manifest_path=manifest_path, output=output, keep_audio=keep_audio)


@app.command()
def status(
    ctx: typer.Context,
    manifest_path: Path = typer.Argument(..., help="manifest.json 路径。"),
    refresh: bool = typer.Option(False, "--refresh", help="调用火山方舟刷新远端任务状态。"),
) -> None:
    """查看本地 manifest 状态和失败原因。"""
    if refresh:
        refresh_status(config=ctx.obj, manifest_path=manifest_path)
    manifest = Manifest.load(manifest_path)
    for line in summarize_status(manifest):
        typer.echo(line)


@app.command()
def run(
    ctx: typer.Context,
    video: Path = typer.Argument(..., help="输入视频路径。"),
    output: Path = typer.Option(..., "-o", "--output", help="任务输出目录。"),
    target: str = typer.Option("auto-opposite", "--target", help="9:16、16:9 或 auto-opposite。"),
    segment_seconds: int = typer.Option(15, "--segment-seconds", "-s", help="每段最大秒数，范围 2-15。"),
    prompt: str = typer.Option("", "--prompt", help="追加提示词。"),
    asset_uris: str = typer.Option("", "--asset-uris", help="逗号分隔的 asset:// URI，数量需等于片段数。"),
    asset_map: Optional[Path] = typer.Option(None, "--asset-map", help="私域人像/视频素材清单 JSON。"),
    split_strategy: str = typer.Option("scene", "--split-strategy", help="scene 或 uniform。"),
    scene_threshold: float = typer.Option(0.28, "--scene-threshold", help="FFmpeg scene 检测阈值。"),
    continuity: str = typer.Option("always", "--continuity", help="always、scene-tail 或 off。"),
    reference_audio: bool = typer.Option(True, "--reference-audio/--no-reference-audio", help="参考片段保留原音频，用于口型和说话人判断。"),
    generation_duration_mode: str = typer.Option("auto", "--generation-duration-mode", help="auto 使用 Seedance 自动时长；ceil 使用整数秒。"),
    alignment_mode: str = typer.Option("trim-pad", "--alignment-mode", help="trim-pad 不变速裁剪/补尾；speed 整体变速对齐。"),
    auto_asset_ingest: bool = typer.Option(False, "--auto-asset-ingest", help="拆分后自动上传 TOS 并录入 Ark 私域素材库。"),
    asset_group_id: str = typer.Option("", "--asset-group-id", help="使用已有 Ark 素材组 ID。"),
    asset_group_name: str = typer.Option("", "--asset-group-name", help="自动创建/复用的 Ark 素材组名称。"),
    asset_project_name: str = typer.Option("", "--asset-project-name", help="Ark 资源所属 ProjectName，默认 default。"),
    keep_audio: bool = typer.Option(True, "--keep-audio/--no-keep-audio", help="合回原音轨。"),
    final_output: Optional[Path] = typer.Option(None, "--final-output", help="最终成片路径，默认 job/final.mp4。"),
    stop_on_error: bool = typer.Option(False, "--stop-on-error", help="任一片段失败后停止。"),
) -> None:
    """一键执行：split -> upload -> remake -> merge。"""
    manifest_path = split_job(
        config=ctx.obj,
        video=video,
        output=output,
        target=target,
        segment_seconds=segment_seconds,
        prompt=prompt,
        asset_uris=parse_asset_uris(asset_uris),
        asset_map_path=asset_map,
        split_strategy=split_strategy,
        scene_threshold=scene_threshold,
        continuity=continuity,
        reference_audio=reference_audio,
        generation_duration_mode=generation_duration_mode,
        alignment_mode=alignment_mode,
        no_upload=True,
        auto_asset_ingest=auto_asset_ingest,
        asset_group_id=asset_group_id,
        asset_group_name=asset_group_name,
        asset_project_name=asset_project_name,
        keep_audio=keep_audio,
    )
    manifest = Manifest.load(manifest_path)
    if manifest.source_reference_mode == "tos":
        upload_job(config=ctx.obj, manifest_path=manifest_path)
    remake_job(
        config=ctx.obj,
        manifest_path=manifest_path,
        continue_on_error=not stop_on_error,
    )
    merge_job(manifest_path=manifest_path, output=final_output, keep_audio=keep_audio)


def _render_error(error: SeedanceAspectError, as_json: bool) -> None:
    if as_json:
        typer.echo(
            json.dumps(
                {"code": error.code, "message": error.message, "request_id": error.request_id},
                ensure_ascii=False,
            ),
            err=True,
        )
        return
    request = f" request_id={error.request_id}" if error.request_id else ""
    typer.echo(f"[{error.code}] {error.message}{request}", err=True)


def main() -> None:
    try:
        app()
    except SeedanceAspectError as exc:
        _render_error(exc, as_json="--json" in sys.argv)
        raise typer.Exit(exc.exit_code) from None


if __name__ == "__main__":
    main()
