"""Seedance 2.0 task submission, polling, and payload creation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from seedance_aspect.ark import ArkClient
from seedance_aspect.errors import ServerError


@dataclass
class VideoGenerateRequest:
    model: str
    prompt: str
    ratio: str
    duration: int
    resolution: str
    reference_uris: List[str]
    safety_identifier: str = ""
    watermark: bool = False
    generate_audio: bool = False

    def to_payload(self) -> Dict[str, Any]:
        content: List[Dict[str, Any]] = []
        prompt = self.prompt.strip()
        if prompt:
            content.append({"type": "text", "text": prompt})
        for uri in self.reference_uris:
            content.append(
                {
                    "type": "video_url",
                    "video_url": {"url": uri},
                    "role": "reference_video",
                }
            )
        payload: Dict[str, Any] = {
            "model": self.model,
            "content": content,
            "ratio": self.ratio,
            "duration": self.duration,
            "resolution": self.resolution,
            "watermark": self.watermark,
            "generate_audio": self.generate_audio,
        }
        if self.safety_identifier:
            payload["safety_identifier"] = self.safety_identifier
        return payload


@dataclass
class SubmitResult:
    task_id: str
    request_id: Optional[str] = None


@dataclass
class TaskStatus:
    task_id: str
    status: str
    file_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    fail_reason: Optional[str] = None
    request_id: Optional[str] = None


class SeedanceClient:
    def __init__(self, client: ArkClient, submit_endpoint: str, status_endpoint_template: str) -> None:
        self.client = client
        self.submit_endpoint = submit_endpoint
        self.status_endpoint_template = status_endpoint_template

    def submit(self, request: VideoGenerateRequest) -> SubmitResult:
        payload, request_id = self.client.post(self.submit_endpoint, request.to_payload())
        task_id = (
            payload.get("id")
            or payload.get("task_id")
            or payload.get("data", {}).get("id")
            or payload.get("data", {}).get("task_id")
        )
        if not task_id:
            raise ServerError("Seedance 提交响应中没有 task_id。", request_id=request_id)
        return SubmitResult(task_id=str(task_id), request_id=request_id)

    def status(self, task_id: str) -> TaskStatus:
        endpoint = self.status_endpoint_template.format(task_id=task_id)
        payload, request_id = self.client.get(endpoint)
        data = payload.get("data", payload)
        status = str(data.get("status") or payload.get("status") or data.get("state") or "unknown")
        content = data.get("content") or {}
        file_url = None
        last_frame_url = None
        if isinstance(content, dict):
            file_url = (
                content.get("video_url")
                or content.get("file_url")
                or (content.get("video") or {}).get("url")
            )
            last_frame_url = content.get("last_frame_url") or (content.get("video") or {}).get("last_frame_url")
        file_url = file_url or data.get("url") or data.get("video_url") or data.get("file_url")
        last_frame_url = last_frame_url or data.get("last_frame_url")
        fail_reason = data.get("reason") or data.get("error_message")
        error_obj = data.get("error") or payload.get("error")
        if not fail_reason and isinstance(error_obj, dict):
            code = error_obj.get("code") or ""
            message = error_obj.get("message") or ""
            fail_reason = f"[{code}] {message}".strip()
        return TaskStatus(
            task_id=task_id,
            status=status,
            file_url=file_url,
            last_frame_url=last_frame_url,
            fail_reason=fail_reason,
            request_id=request_id,
        )


def normalize_status(status: str) -> str:
    value = status.lower()
    if value in {"succeeded", "success", "completed", "done"}:
        return "succeeded"
    if value in {"failed", "fail", "error", "cancelled", "canceled", "expired"}:
        return "failed"
    if value in {"queued", "pending", "running", "processing", "in_progress", "created"}:
        return "running"
    return value


def poll_task(
    fetcher: Callable[[str], TaskStatus],
    task_id: str,
    *,
    interval_s: int,
    max_wait_s: int,
    on_update: Optional[Callable[[TaskStatus, str], None]] = None,
) -> TaskStatus:
    deadline = time.monotonic() + max_wait_s
    last_normalized = ""
    while True:
        result = fetcher(task_id)
        normalized = normalize_status(result.status)
        if normalized != last_normalized and on_update:
            on_update(result, normalized)
        last_normalized = normalized
        if normalized in {"succeeded", "failed"}:
            return result
        if time.monotonic() >= deadline:
            return TaskStatus(task_id=task_id, status="expired", fail_reason="轮询超时。")
        time.sleep(interval_s)

