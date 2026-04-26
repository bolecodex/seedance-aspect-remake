"""Upload reference segments to Volcengine TOS."""

from __future__ import annotations

import uuid
from pathlib import Path
from seedance_aspect.config import TOSConfig
from seedance_aspect.errors import ConfigError


def upload_file(path: Path, tos_config: TOSConfig, *, prefix: str = "seedance-aspect/segments/") -> str:
    try:
        import tos
    except ImportError as exc:
        raise ConfigError("缺少 tos 依赖。请执行 pip install -e . 或 pip install tos。") from exc

    client = tos.TosClientV2(
        tos_config.access_key,
        tos_config.secret_key,
        tos_config.endpoint,
        tos_config.region,
        connection_time=30,
        socket_timeout=300,
    )
    key = f"{prefix}{uuid.uuid4().hex[:10]}_{path.name}"
    client.upload_file(
        tos_config.bucket,
        key,
        str(path),
        part_size=5 * 1024 * 1024,
        task_num=3,
        enable_checkpoint=False,
    )

    signed = client.pre_signed_url(
        tos.HttpMethodType.Http_Method_Get,
        tos_config.bucket,
        key,
        expires=tos_config.signed_url_expires,
    )
    return signed.signed_url
