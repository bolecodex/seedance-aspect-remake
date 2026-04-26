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


def _load_dotenv_from_cwd() -> None:
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        env_file = candidate / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)
            return


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数，当前值为：{raw}") from exc


def load_config(overrides: Optional[Dict[str, Any]] = None) -> AppConfig:
    _load_dotenv_from_cwd()
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
    }
    values.update({k: v for k, v in overrides.items() if v is not None and v != ""})
    return AppConfig(**values)
