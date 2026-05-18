"""Configuration loading for Ark, Seedance, and TOS."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from seedance_aspect.errors import ConfigError


@dataclass
class TOSConfig:
    access_key: str
    secret_key: str
    bucket: str
    endpoint: str = "tos-cn-beijing.volces.com"
    region: str = "cn-beijing"
    signed_url_expires: int = 604800


@dataclass
class ArkAssetsConfig:
    access_key: str
    secret_key: str
    region: str = "cn-beijing"
    base_url: str = "https://open.volcengineapi.com"
    service: str = "ark"
    version: str = "2024-01-01"
    project_name: str = "default"
    group_id: str = ""
    group_name: str = ""
    group_description: str = ""
    poll_interval_s: int = 3
    poll_max_wait_s: int = 3600


@dataclass
class AppConfig:
    api_key: str = ""
    base_url: str = "https://ark.cn-beijing.volces.com"
    video_submit_endpoint: str = "/api/v3/contents/generations/tasks"
    video_status_endpoint_template: str = "/api/v3/contents/generations/tasks/{task_id}"
    model: str = "doubao-seedance-2-0-260128"
    resolution: str = "720p"
    request_timeout_s: int = 120
    poll_interval_s: int = 10
    poll_max_wait_s: int = 1800
    safety_identifier: str = ""
    tos_access_key: str = ""
    tos_secret_key: str = ""
    tos_bucket: str = ""
    tos_endpoint: str = "tos-cn-beijing.volces.com"
    tos_region: str = "cn-beijing"
    tos_signed_url_expires: int = 604800
    asset_base_url: str = "https://open.volcengineapi.com"
    asset_service: str = "ark"
    asset_version: str = "2024-01-01"
    asset_project_name: str = "default"
    asset_group_id: str = ""
    asset_group_name: str = ""
    asset_group_description: str = ""
    asset_poll_interval_s: int = 3
    asset_poll_max_wait_s: int = 3600

    @property
    def tos_available(self) -> bool:
        return bool(self.tos_access_key and self.tos_secret_key and self.tos_bucket)

    def require_api_key(self) -> str:
        if not self.api_key:
            raise ConfigError("缺少 ARK_API_KEY。请在环境变量或 .env 中配置火山方舟 API Key。")
        return self.api_key

    def require_tos(self) -> TOSConfig:
        if not self.tos_available:
            raise ConfigError(
                "视频参考模式需要 TOS：请配置 VOLC_ACCESSKEY、VOLC_SECRETKEY、TOS_BUCKET。"
            )
        return TOSConfig(
            access_key=self.tos_access_key,
            secret_key=self.tos_secret_key,
            bucket=self.tos_bucket,
            endpoint=self.tos_endpoint,
            region=self.tos_region,
            signed_url_expires=self.tos_signed_url_expires,
        )

    def require_assets(self) -> ArkAssetsConfig:
        if not self.tos_access_key or not self.tos_secret_key:
            raise ConfigError(
                "自动录入私域素材库需要 VOLC_ACCESSKEY 和 VOLC_SECRETKEY。"
            )
        return ArkAssetsConfig(
            access_key=self.tos_access_key,
            secret_key=self.tos_secret_key,
            region=self.tos_region,
            base_url=self.asset_base_url,
            service=self.asset_service,
            version=self.asset_version,
            project_name=self.asset_project_name,
            group_id=self.asset_group_id,
            group_name=self.asset_group_name,
            group_description=self.asset_group_description,
            poll_interval_s=self.asset_poll_interval_s,
            poll_max_wait_s=self.asset_poll_max_wait_s,
        )


def _load_dotenv_files() -> None:
    candidates = []

    explicit = os.getenv("SEEDANCE_ASPECT_ENV")
    if explicit:
        candidates.append(Path(explicit).expanduser())

    for candidate in [Path.cwd(), *Path.cwd().parents]:
        env_file = candidate / ".env"
        candidates.append(env_file)

    home = Path.home()
    configured_home = os.getenv("SEEDANCE_ASPECT_HOME")
    if configured_home:
        candidates.append(Path(configured_home).expanduser() / ".env")
    candidates.append(home / ".local" / "share" / "seedance-aspect-remake" / ".env")

    # Editable installs used by setup-gitee.sh keep src/ under the repository root.
    candidates.append(Path(__file__).resolve().parents[2] / ".env")

    seen = set()
    for env_file in candidates:
        resolved = env_file.resolve() if env_file.exists() else env_file
        if resolved in seen:
            continue
        seen.add(resolved)
        if env_file.is_file():
            load_dotenv(env_file, override=False)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数，当前值为：{raw}") from exc


def load_config(overrides: Optional[Dict[str, Any]] = None) -> AppConfig:
    _load_dotenv_files()
    overrides = overrides or {}

    values: Dict[str, Any] = {
        "api_key": os.getenv("ARK_API_KEY", ""),
        "base_url": os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com"),
        "model": (
            os.getenv("SEEDANCE_MODEL")
            or os.getenv("SEEDANCE_ENDPOINT")
            or "doubao-seedance-2-0-260128"
        ),
        "resolution": os.getenv("SEEDANCE_RESOLUTION", "720p"),
        "request_timeout_s": _env_int("SEEDANCE_REQUEST_TIMEOUT", 120),
        "poll_interval_s": _env_int("SEEDANCE_POLL_INTERVAL", 10),
        "poll_max_wait_s": _env_int("SEEDANCE_POLL_MAX_WAIT", 1800),
        "safety_identifier": os.getenv("SEEDANCE_SAFETY_IDENTIFIER", ""),
        "tos_access_key": os.getenv("VOLC_ACCESSKEY", ""),
        "tos_secret_key": os.getenv("VOLC_SECRETKEY", ""),
        "tos_bucket": os.getenv("TOS_BUCKET", ""),
        "tos_endpoint": os.getenv("TOS_ENDPOINT", "tos-cn-beijing.volces.com"),
        "tos_region": os.getenv("TOS_REGION") or os.getenv("OS_REGION") or "cn-beijing",
        "tos_signed_url_expires": _env_int("TOS_SIGNED_URL_EXPIRES", 604800),
        "asset_base_url": os.getenv("ARK_ASSET_BASE_URL", "https://open.volcengineapi.com"),
        "asset_service": os.getenv("ARK_ASSET_SERVICE", "ark"),
        "asset_version": os.getenv("ARK_ASSET_VERSION", "2024-01-01"),
        "asset_project_name": os.getenv("ARK_ASSET_PROJECT_NAME", "default"),
        "asset_group_id": os.getenv("ARK_ASSET_GROUP_ID", ""),
        "asset_group_name": os.getenv("ARK_ASSET_GROUP_NAME", ""),
        "asset_group_description": os.getenv("ARK_ASSET_GROUP_DESCRIPTION", ""),
        "asset_poll_interval_s": _env_int("ARK_ASSET_POLL_INTERVAL", 3),
        "asset_poll_max_wait_s": _env_int("ARK_ASSET_POLL_MAX_WAIT", 3600),
    }
    values.update({k: v for k, v in overrides.items() if v is not None and v != ""})
    return AppConfig(**values)
