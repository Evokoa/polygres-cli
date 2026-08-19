from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from polygres_cli.cli_errors import (
    UNAVAILABLE,
    CliError,
    api_error_from_response,
    is_maintenance_error_payload,
)

GrantProvider = Callable[[str, str], dict[str, Any]]
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
MANAGED_RUNTIME_API_DOMAINS = frozenset(
    {
        "api.db.polygres.com",
        "api.staging.db.polygres.com",
    }
)


class RuntimeClient:
    def __init__(
        self,
        *,
        grant_provider: GrantProvider,
        http_client: httpx.Client,
        now: Callable[[], datetime] | None = None,
        max_retries: int = 2,
        allow_local_http: bool = False,
        telemetry_headers: dict[str, str] | None = None,
    ) -> None:
        self._grant_provider = grant_provider
        self._client = http_client
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._max_retries = max_retries
        self._allow_local_http = allow_local_http
        self._telemetry_headers = dict(telemetry_headers or {})
        self._grants: dict[tuple[str, str], dict[str, Any]] = {}

    def clear(self) -> None:
        self._grants.clear()

    def get(self, project_id: str, scope: str, path: str) -> dict[str, Any]:
        return self.request(project_id, scope, "GET", path)

    def request(
        self,
        project_id: str,
        scope: str,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
        read_only_retry: bool = False,
        allow_auth_replay: bool = True,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        method = method.upper()
        refreshed_after_401 = False
        network_attempt = 0
        while True:
            grant = self._grant(project_id, scope)
            runtime_api_url = str(grant["runtime_api_url"])
            url = f"{runtime_api_url}{path}"
            request_headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {grant['access_token']}",
                **self._telemetry_headers,
                **(headers or {}),
            }
            if json is not None:
                request_headers["Content-Type"] = "application/json"
            try:
                response = self._client.request(
                    method,
                    url,
                    headers=request_headers,
                    json=json,
                    timeout=timeout,
                )
            except (httpx.TimeoutException, httpx.NetworkError):
                if (method == "GET" or read_only_retry) and network_attempt < self._max_retries:
                    network_attempt += 1
                    continue
                raise
            if response.status_code == 401 and allow_auth_replay and not refreshed_after_401:
                refreshed_after_401 = True
                self._grants.pop((project_id, scope), None)
                continue
            payload = _json_payload(response)
            if is_maintenance_error_payload(payload):
                raise api_error_from_response(response.status_code, payload)
            if (
                (method == "GET" or read_only_retry)
                and response.status_code in RETRY_STATUSES
                and network_attempt < self._max_retries
            ):
                network_attempt += 1
                _wait_for_retry_after(response)
                continue
            if response.is_error:
                raise api_error_from_response(response.status_code, payload)
            if response.content and not payload:
                raise CliError(
                    "RUNTIME_RESPONSE_INVALID",
                    "The Runtime API returned an invalid response. Please wait a while and "
                    "retry the command. If it continues, contact support with the command "
                    "and project ID.",
                    exit_code=UNAVAILABLE,
                )
            return payload

    def _grant(self, project_id: str, scope: str) -> dict[str, Any]:
        if scope not in {"graph:read", "graph:manage", "rows:write"}:
            raise ValueError("Runtime grant scope is invalid")
        key = (project_id, scope)
        cached = self._grants.get(key)
        skew = 30 if scope == "graph:read" else 10
        if cached is not None and _expiry(cached) - skew > self._now().timestamp():
            return cached
        value = self._grant_provider(project_id, scope)
        if value.get("project_id") != project_id or value.get("scope") != scope:
            raise CliError(
                "RUNTIME_GRANT_INVALID",
                "The Runtime API returned an access grant for a different project or scope. "
                "Retry the command; contact support if the response remains invalid.",
                exit_code=UNAVAILABLE,
            )
        token = value.get("access_token")
        if not isinstance(token, str) or not token:
            raise CliError(
                "RUNTIME_GRANT_INVALID",
                "The Runtime API returned an incomplete access grant. Retry the command. "
                "If it happens again, contact support.",
                exit_code=UNAVAILABLE,
            )
        try:
            runtime_api_url = validate_runtime_api_url(
                str(value.get("runtime_api_url") or ""),
                project_id,
                allow_local_http=self._allow_local_http,
            )
        except ValueError as exc:
            request_id = value.get("request_id")
            raise CliError(
                "RUNTIME_GRANT_INVALID",
                "The Runtime API returned an invalid access URL. Retry the command. "
                "If it happens again, contact support.",
                exit_code=UNAVAILABLE,
                request_id=request_id if isinstance(request_id, str) else None,
            ) from exc
        if _expiry(value) <= self._now().timestamp():
            raise CliError(
                "RUNTIME_GRANT_INVALID",
                "The Runtime API returned an expired access grant. Retry the command to request "
                "a new grant. If the new grant is also expired, contact support.",
                exit_code=UNAVAILABLE,
            )
        normalized = dict(value)
        normalized["runtime_api_url"] = runtime_api_url
        self._grants[key] = normalized
        return normalized


def validate_runtime_api_url(value: str, project_id: str, *, allow_local_http: bool = False) -> str:
    parsed = urlsplit(value)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    managed_hosts = {
        f"{project_id}.{runtime_domain}" for runtime_domain in MANAGED_RUNTIME_API_DOMAINS
    }
    if (
        not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or (parsed.port is not None and not (allow_local_http and loopback))
        or parsed.query
        or parsed.fragment
        or parsed.path != "/v1"
        or (
            parsed.scheme != "https"
            and not (allow_local_http and parsed.scheme == "http" and loopback)
        )
        or (
            not (allow_local_http and loopback)
            and parsed.hostname not in managed_hosts
        )
    ):
        raise ValueError("Runtime API URL is invalid")
    return value.rstrip("/")


def _expiry(payload: dict[str, Any]) -> float:
    value = payload.get("expires_at")
    if not isinstance(value, str):
        return 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def _json_payload(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _wait_for_retry_after(response: httpx.Response) -> None:
    value = response.headers.get("retry-after")
    if not value:
        return
    try:
        delay = float(value)
    except ValueError:
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            return
    if delay > 0:
        time.sleep(min(delay, 5.0))
