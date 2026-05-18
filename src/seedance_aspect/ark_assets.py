"""Invite-only Ark Assets API client for private portrait/video assets."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlsplit

import httpx

from seedance_aspect.config import ArkAssetsConfig
from seedance_aspect.errors import AuthError, NetworkError, RequestError, ServerError


@dataclass
class AssetPollResult:
    asset_id: str
    status: str
    raw: Dict[str, Any]

    @property
    def error_message(self) -> str:
        error = self.raw.get("Error") or self.raw.get("error") or {}
        if isinstance(error, dict):
            code = str(error.get("Code") or error.get("code") or "").strip()
            message = str(error.get("Message") or error.get("message") or "").strip()
            return f"[{code}] {message}".strip()
        return str(error or "").strip()


class ArkAssetsClient:
    def __init__(self, config: ArkAssetsConfig, *, http_client: Optional[httpx.Client] = None) -> None:
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._http_client = http_client

    def close(self) -> None:
        if self._http_client is not None:
            self._http_client.close()

    def create_asset_group(
        self,
        *,
        name: str,
        description: str = "",
        project_name: Optional[str] = None,
    ) -> str:
        result = self.call(
            "CreateAssetGroup",
            {
                "Name": name,
                "Description": description,
                "GroupType": "AIGC",
                "ProjectName": project_name or self.config.project_name,
            },
        )
        group_id = result.get("Id") or result.get("id")
        if not group_id:
            raise ServerError("CreateAssetGroup 响应中没有素材组 Id。")
        return str(group_id)

    def list_asset_groups(
        self,
        *,
        name: str = "",
        project_name: Optional[str] = None,
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        body: Dict[str, Any] = {
            "Filter": {"GroupType": "AIGC"},
            "PageNumber": 1,
            "PageSize": page_size,
            "ProjectName": project_name or self.config.project_name,
        }
        if name:
            body["Filter"]["Name"] = name
        result = self.call("ListAssetGroups", body)
        items = result.get("Items") or result.get("items") or []
        return [dict(item) for item in items if isinstance(item, dict)]

    def ensure_asset_group(
        self,
        *,
        group_id: str = "",
        group_name: str = "",
        description: str = "",
        project_name: Optional[str] = None,
    ) -> str:
        if group_id:
            return group_id
        if not group_name:
            raise RequestError("未指定素材组。请传入 --asset-group-id 或 --asset-group-name。")
        for item in self.list_asset_groups(name=group_name, project_name=project_name):
            if str(item.get("Name") or item.get("name") or "") == group_name:
                found = item.get("Id") or item.get("id")
                if found:
                    return str(found)
        return self.create_asset_group(
            name=group_name,
            description=description,
            project_name=project_name,
        )

    def create_asset(
        self,
        *,
        group_id: str,
        url: str,
        asset_type: str,
        name: str = "",
        project_name: Optional[str] = None,
    ) -> str:
        result = self.call(
            "CreateAsset",
            {
                "GroupId": group_id,
                "URL": url,
                "Name": name,
                "AssetType": asset_type,
                "ProjectName": project_name or self.config.project_name,
            },
        )
        asset_id = result.get("Id") or result.get("id")
        if not asset_id:
            raise ServerError("CreateAsset 响应中没有素材 Id。")
        return str(asset_id)

    def get_asset(self, asset_id: str, *, project_name: Optional[str] = None) -> Dict[str, Any]:
        result = self.call(
            "GetAsset",
            {"Id": asset_id, "ProjectName": project_name or self.config.project_name},
        )
        return dict(result)

    def wait_asset_active(
        self,
        asset_id: str,
        *,
        project_name: Optional[str] = None,
        interval_s: Optional[int] = None,
        max_wait_s: Optional[int] = None,
        on_update: Optional[Any] = None,
    ) -> AssetPollResult:
        interval = self.config.poll_interval_s if interval_s is None else interval_s
        max_wait = self.config.poll_max_wait_s if max_wait_s is None else max_wait_s
        deadline = time.monotonic() + max_wait
        last_status = ""
        while True:
            raw = self.get_asset(asset_id, project_name=project_name)
            status = str(raw.get("Status") or raw.get("status") or "Unknown")
            if status != last_status and on_update:
                on_update(raw, status)
            last_status = status
            normalized = status.lower()
            if normalized in {"active", "failed"}:
                return AssetPollResult(asset_id=asset_id, status=status, raw=raw)
            if time.monotonic() >= deadline:
                return AssetPollResult(
                    asset_id=asset_id,
                    status="Failed",
                    raw={"Id": asset_id, "Status": "Failed", "Error": {"Message": "素材入库轮询超时。"}},
                )
            time.sleep(interval)

    def call(self, action: str, body: Mapping[str, Any]) -> Dict[str, Any]:
        payload = json.dumps(dict(body), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        url, headers = self._signed_request(action, payload)
        try:
            response = self._client().post(url, content=payload, headers=headers)
        except httpx.RequestError as exc:
            raise NetworkError(f"调用 Ark Assets API 失败：{exc}") from exc

        request_id = _request_id(response)
        if response.status_code in (401, 403):
            raise AuthError(_extract_error_message(response) or "Ark Assets API 鉴权失败。", request_id=request_id)
        if 400 <= response.status_code < 500:
            raise RequestError(
                _extract_error_message(response) or f"Ark Assets API 请求被拒绝：HTTP {response.status_code}",
                request_id=request_id,
            )
        if response.status_code >= 500:
            raise ServerError(
                _extract_error_message(response) or f"Ark Assets API 服务错误：HTTP {response.status_code}",
                request_id=request_id,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ServerError("Ark Assets API 响应不是有效 JSON。", request_id=request_id) from exc

        metadata = data.get("ResponseMetadata") or {}
        error = metadata.get("Error") if isinstance(metadata, dict) else None
        if isinstance(error, dict):
            code = str(error.get("Code") or error.get("code") or "").strip()
            message = str(error.get("Message") or error.get("message") or "").strip()
            rendered = f"[{code}] {message}".strip()
            if "auth" in code.lower() or "unauthorized" in code.lower():
                raise AuthError(rendered or "Ark Assets API 鉴权失败。", request_id=request_id)
            raise RequestError(rendered or "Ark Assets API 请求失败。", request_id=request_id)

        result = data.get("Result") or data.get("result")
        if not isinstance(result, dict):
            raise ServerError("Ark Assets API 响应中没有 Result 对象。", request_id=request_id)
        return result

    def _client(self) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        self._http_client = httpx.Client(timeout=120)
        return self._http_client

    def _signed_request(self, action: str, payload: bytes) -> Tuple[str, Dict[str, str]]:
        parsed = urlsplit(self.base_url)
        scheme = parsed.scheme or "https"
        host = parsed.netloc or parsed.path
        path = parsed.path if parsed.netloc else "/"
        if not path:
            path = "/"
        existing_query = _parse_query(parsed.query)
        query = {**existing_query, "Action": action, "Version": self.config.version}
        query_string = _canonical_query(query)
        endpoint = f"{scheme}://{host}{path}?{query_string}"

        now = datetime.now(timezone.utc)
        x_date = now.strftime("%Y%m%dT%H%M%SZ")
        short_date = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(payload).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "Host": host,
            "X-Content-Sha256": payload_hash,
            "X-Date": x_date,
        }
        signed_headers = "content-type;host;x-content-sha256;x-date"
        canonical_headers = (
            f"content-type:{headers['Content-Type']}\n"
            f"host:{headers['Host']}\n"
            f"x-content-sha256:{headers['X-Content-Sha256']}\n"
            f"x-date:{headers['X-Date']}\n"
        )
        canonical_request = "\n".join(
            [
                "POST",
                path,
                query_string,
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        scope = f"{short_date}/{self.config.region}/{self.config.service}/request"
        string_to_sign = "\n".join(
            [
                "HMAC-SHA256",
                x_date,
                scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(
            _signing_key(self.config.secret_key, short_date, self.config.region, self.config.service),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["Authorization"] = (
            f"HMAC-SHA256 Credential={self.config.access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return endpoint, headers


def _canonical_query(query: Mapping[str, str]) -> str:
    return "&".join(
        f"{quote(str(key), safe='-_.~')}={quote(str(value), safe='-_.~')}"
        for key, value in sorted(query.items())
    )


def _parse_query(raw: str) -> Dict[str, str]:
    if not raw:
        return {}
    pairs = {}
    for item in raw.split("&"):
        if not item:
            continue
        key, _, value = item.partition("=")
        pairs[key] = value
    return pairs


def _signing_key(secret_key: str, date: str, region: str, service: str) -> bytes:
    key = hmac.new(secret_key.encode("utf-8"), date.encode("utf-8"), hashlib.sha256).digest()
    key = hmac.new(key, region.encode("utf-8"), hashlib.sha256).digest()
    key = hmac.new(key, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(key, b"request", hashlib.sha256).digest()


def _request_id(response: httpx.Response) -> Optional[str]:
    try:
        payload = response.json()
    except ValueError:
        return response.headers.get("x-tt-logid") or response.headers.get("x-request-id")
    metadata = payload.get("ResponseMetadata") if isinstance(payload, dict) else None
    if isinstance(metadata, dict):
        return str(metadata.get("RequestId") or "") or None
    return response.headers.get("x-tt-logid") or response.headers.get("x-request-id")


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    if not isinstance(payload, dict):
        return str(payload)[:500]
    metadata = payload.get("ResponseMetadata") or {}
    if isinstance(metadata, dict):
        error = metadata.get("Error")
        if isinstance(error, dict):
            code = error.get("Code") or error.get("code") or ""
            message = error.get("Message") or error.get("message") or ""
            return f"[{code}] {message}".strip()
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code") or error.get("Code") or ""
        message = error.get("message") or error.get("Message") or ""
        return f"[{code}] {message}".strip()
    return str(payload.get("message") or payload.get("msg") or "")
