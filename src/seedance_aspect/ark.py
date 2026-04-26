"""Small HTTP client for Ark data-plane APIs."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import httpx

from seedance_aspect.errors import AuthError, NetworkError, RequestError, ServerError


class ArkClient:
    def __init__(self, *, api_key: str, base_url: str, timeout_s: int = 120) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def post(self, endpoint: str, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
        return self._request("POST", endpoint, json=payload)

    def get(self, endpoint: str) -> Tuple[Dict[str, Any], Optional[str]]:
        return self._request("GET", endpoint)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Tuple[Dict[str, Any], Optional[str]]:
        url = f"{self.base_url}{endpoint}"
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                response = client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.RequestError as exc:
            raise NetworkError(f"调用火山方舟失败：{exc}") from exc

        request_id = response.headers.get("x-tt-logid") or response.headers.get("x-request-id")
        message = self._extract_error_message(response)
        if response.status_code in (401, 403):
            raise AuthError(message or "火山方舟鉴权失败。", request_id=request_id)
        if 400 <= response.status_code < 500:
            raise RequestError(message or f"请求被拒绝：HTTP {response.status_code}", request_id=request_id)
        if response.status_code >= 500:
            raise ServerError(message or f"火山方舟服务错误：HTTP {response.status_code}", request_id=request_id)
        try:
            return response.json(), request_id
        except ValueError as exc:
            raise ServerError("火山方舟响应不是有效 JSON。", request_id=request_id) from exc

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                code = error.get("code") or ""
                message = error.get("message") or ""
                return f"[{code}] {message}".strip()
            return str(payload.get("message") or payload.get("msg") or "")
        return ""

