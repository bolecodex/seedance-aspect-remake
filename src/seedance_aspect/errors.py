"""Typed errors for user-facing CLI failures."""

from __future__ import annotations

from typing import Optional


class SeedanceAspectError(Exception):
    code = "seedance_aspect_error"
    exit_code = 1

    def __init__(self, message: str, *, request_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id


class ConfigError(SeedanceAspectError):
    code = "config_error"


class FFmpegError(SeedanceAspectError):
    code = "ffmpeg_error"


class ManifestError(SeedanceAspectError):
    code = "manifest_error"


class NetworkError(SeedanceAspectError):
    code = "network_error"


class AuthError(SeedanceAspectError):
    code = "auth_error"


class RequestError(SeedanceAspectError):
    code = "request_error"


class ServerError(SeedanceAspectError):
    code = "server_error"
