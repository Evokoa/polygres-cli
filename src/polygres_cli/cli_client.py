from __future__ import annotations

import base64
import hashlib
import json as jsonlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx

from polygres_cli._version import __version__
from polygres_cli.api_openapi import ApiRequestPlan
from polygres_cli.cli_auth import (
    normalize_poll_response,
    normalize_refresh_response,
    poll_request,
    refresh_request,
    revoke_request,
    start_request,
)
from polygres_cli.cli_errors import (
    AUTH,
    UNAVAILABLE,
    CliError,
    api_error_from_response,
    is_maintenance_error_payload,
)
from polygres_cli.cli_secrets import redact_string
from polygres_cli.runtime_client import RuntimeClient

RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
HEAVY_REQUEST_TIMEOUT = 120.0


@dataclass(frozen=True, slots=True)
class ContextPollResponse:
    envelope: dict[str, Any]
    retry_after_seconds: float | None


class CliControlPlaneClient:
    def __init__(
        self,
        *,
        base_url: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        on_token_refresh: Callable[[dict[str, Any]], None] | None = None,
        on_refresh_auth_failure: Callable[[], None] | None = None,
        verbose: bool = False,
        trace: Callable[[str], None] | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._on_token_refresh = on_token_refresh
        self._on_refresh_auth_failure = on_refresh_auth_failure
        self._refresh_attempted = False
        self._verbose = verbose
        self._trace = trace
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = httpx.Client(timeout=timeout)
        self._direct_runtime_graph = _enabled("CLI_DIRECT_RUNTIME_GRAPH_ENABLED")
        self._runtime = RuntimeClient(
            grant_provider=self.runtime_access,
            http_client=self._client,
            max_retries=max_retries,
            allow_local_http=urlsplit(self._base_url).hostname in {"localhost", "127.0.0.1", "::1"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CliControlPlaneClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def start_login(self, client: dict[str, Any]) -> dict[str, Any]:
        version = client.get("version")
        if not isinstance(version, str):
            raise CliError("INVALID_USAGE", "CLI version is required.", exit_code=2)
        return self._post("/cli/auth/start", start_request(version=version), auth=False)

    def poll_login(
        self, login_session_id: str, poll_token: str, *, deadline: float | None = None
    ) -> dict[str, Any]:
        return normalize_poll_response(
            self._post(
                "/cli/auth/poll",
                poll_request(login_session_id=login_session_id, poll_token=poll_token),
                auth=False,
                retry=True,
                deadline=deadline,
            )
        )

    def refresh_login(self, refresh_token: str) -> dict[str, Any]:
        return normalize_refresh_response(
            self._post(
                "/cli/auth/refresh",
                refresh_request(refresh_token=refresh_token),
                auth=False,
            )
        )

    def revoke_login(self, refresh_token: str) -> dict[str, Any]:
        return self._post(
            "/cli/auth/revoke", revoke_request(refresh_token=refresh_token), auth=False
        )

    def me(self) -> dict[str, Any]:
        return self._get("/me")

    def list_projects(self) -> dict[str, Any]:
        return self._get("/projects")

    def get_project(self, project_id: str) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}")

    def create_project(
        self,
        name: str,
        *,
        request_timeout: float | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        return self._post("/projects", {"name": name}, timeout=request_timeout, deadline=deadline)

    def get_project_status(
        self, project_id: str, *, deadline: float | None = None
    ) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}/status", deadline=deadline)

    def connection_info(self, project_id: str) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}/connection-info")

    def list_api_keys(self, project_id: str) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}/api-keys")

    def create_api_key(self, project_id: str, name: str) -> dict[str, Any]:
        return self._post(f"/projects/{project_id}/api-keys", {"name": name})

    def revoke_api_key(self, project_id: str, key_id: str) -> dict[str, Any]:
        return self._delete(f"/projects/{project_id}/api-keys/{key_id}")

    def csv_preview(self, project_id: str, file: Path, fields: dict[str, str]) -> dict[str, Any]:
        file_size = file.stat().st_size
        session = self._post(
            f"/projects/{project_id}/imports/csv/upload-sessions",
            {"original_filename": file.name, "file_size_bytes": file_size},
        )
        upload = session.get("upload")
        if not isinstance(upload, dict):
            raise CliError(
                "IMPORT_INVALID",
                "The API returned an invalid CSV upload session. Retry the import. "
                "If it happens again, contact support.",
                request_id=(
                    str(session.get("request_id")) if session.get("request_id") else None
                ),
            )
        job_id = upload.get("job_id")
        upload_url = upload.get("upload_url")
        block_size = upload.get("block_size_bytes")
        if (
            not isinstance(job_id, str)
            or not isinstance(upload_url, str)
            or isinstance(block_size, bool)
            or not isinstance(block_size, int)
            or block_size <= 0
        ):
            raise CliError(
                "IMPORT_INVALID",
                "The API returned an incomplete CSV upload session. Retry the import. "
                "If it happens again, contact support.",
                request_id=(
                    str(session.get("request_id")) if session.get("request_id") else None
                ),
            )
        sha256 = self._upload_csv_blocks(file, upload_url, block_size)
        payload: dict[str, Any] = {
            "job_id": job_id,
            "original_filename": file.name,
            "file_size_bytes": file_size,
            "sha256": sha256,
            "target_schema": fields.get("target_schema", "public"),
            "target_table": fields.get("target_table"),
            "mode": fields.get("mode", "create_table"),
            "encoding": fields.get("encoding", "utf-8"),
            "quote_char": fields.get("quote_char", '"'),
            "has_header": fields.get("has_header", "true") == "true",
            "sample_row_count": int(fields.get("sample_row_count", "50")),
        }
        for name in ("delimiter", "escape_char"):
            if name in fields:
                payload[name] = fields[name]
        return self._post(
            f"/projects/{project_id}/imports/csv/upload-sessions/{job_id}/complete",
            payload,
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def _upload_csv_blocks(self, file: Path, upload_url: str, block_size: int) -> str:
        digest = hashlib.sha256()
        block_ids: list[str] = []
        with file.open("rb") as handle:
            index = 0
            while chunk := handle.read(block_size):
                digest.update(chunk)
                block_id = base64.b64encode(f"{index:08d}".encode()).decode()
                block_ids.append(block_id)
                block_url = f"{upload_url}&comp=block&blockid={quote(block_id, safe='')}"
                self._blob_request(
                    "PUT",
                    block_url,
                    content=chunk,
                    headers={
                        "Content-MD5": base64.b64encode(
                            hashlib.md5(chunk, usedforsecurity=False).digest()
                        ).decode(),
                        "x-ms-version": "2023-11-03",
                    },
                )
                index += 1
        if block_ids:
            block_list = (
                '<?xml version="1.0" encoding="utf-8"?><BlockList>'
                + "".join(f"<Latest>{block_id}</Latest>" for block_id in block_ids)
                + "</BlockList>"
            )
            self._blob_request(
                "PUT",
                f"{upload_url}&comp=blocklist",
                content=block_list.encode(),
                headers={"Content-Type": "application/xml", "x-ms-version": "2023-11-03"},
            )
        else:
            self._blob_request(
                "PUT",
                upload_url,
                content=b"",
                headers={"x-ms-blob-type": "BlockBlob", "x-ms-version": "2023-11-03"},
            )
        return digest.hexdigest()

    def _blob_request(
        self, method: str, url: str, *, content: bytes, headers: dict[str, str]
    ) -> None:
        response: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.request(
                    method,
                    url,
                    content=content,
                    headers=headers,
                    timeout=HEAVY_REQUEST_TIMEOUT,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < self._max_retries:
                    _sleep_before_retry(attempt, None)
                    continue
                raise CliError(
                    "IMPORT_UPLOAD_FAILED",
                    "Could not reach the CSV upload service. Check the network and proxy "
                    "connection, then retry the import.",
                    exit_code=UNAVAILABLE,
                ) from exc
            if response.status_code in RETRY_STATUSES and attempt < self._max_retries:
                _sleep_before_retry(attempt, response.headers.get("Retry-After"))
                continue
            break
        assert response is not None
        if response.is_error:
            raise CliError(
                "IMPORT_UPLOAD_FAILED",
                f"CSV upload failed with HTTP {response.status_code}. Retry the import to "
                "request a new upload session; contact support if it continues.",
                exit_code=UNAVAILABLE,
            )

    def start_csv_import(self, project_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self._post(
            f"/projects/{project_id}/imports/csv",
            fields,
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def list_imports(self, project_id: str) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}/imports")

    def get_import(
        self, project_id: str, job_id: str, *, deadline: float | None = None
    ) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}/imports/{job_id}", deadline=deadline)

    def migrations_list(self, project_id: str) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}/migrations")

    def migrations_create(self, project_id: str, name: str, sql_body: str) -> dict[str, Any]:
        return self._post(
            f"/projects/{project_id}/migrations",
            {"name": name, "sql_body": sql_body},
        )

    def migrations_apply(self, project_id: str, migration_id: str) -> dict[str, Any]:
        return self._post(
            f"/projects/{project_id}/migrations/{migration_id}/apply",
            {},
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def graph_discover(self, project_id: str) -> dict[str, Any]:
        if self._direct_runtime_graph:
            return self._runtime.request(
                project_id, "graph:read", "POST", "/graph/discover", json={}
            )
        return self._post(f"/projects/{project_id}/graph/discover", {})

    def get_graph_configuration(self, project_id: str) -> dict[str, Any]:
        if self._direct_runtime_graph:
            return self._runtime.get(project_id, "graph:read", "/graph/configuration")
        return self._get(f"/projects/{project_id}/graph/configuration")

    def put_graph_configuration(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._direct_runtime_graph:
            return self._runtime.request(
                project_id,
                "graph:manage",
                "PUT",
                "/graph/configuration",
                json=payload,
                timeout=HEAVY_REQUEST_TIMEOUT,
            )
        return self._put(
            f"/projects/{project_id}/graph/configuration",
            payload,
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def graph_build(self, project_id: str) -> dict[str, Any]:
        if self._direct_runtime_graph:
            return self._runtime.request(
                project_id,
                "graph:manage",
                "POST",
                "/graph/build",
                json={},
                timeout=HEAVY_REQUEST_TIMEOUT,
            )
        return self._post(f"/projects/{project_id}/graph/build", {}, timeout=HEAVY_REQUEST_TIMEOUT)

    def graph_status(self, project_id: str) -> dict[str, Any]:
        if self._direct_runtime_graph:
            return self._runtime.get(project_id, "graph:read", "/graph/status")
        return self._get(f"/projects/{project_id}/graph/status")

    def runtime_access(self, project_id: str, scope: str) -> dict[str, Any]:
        return self._post(
            f"/projects/{project_id}/runtime/access",
            {"scope": scope},
        )

    def list_vector_configurations(self, project_id: str) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}/vector/configurations")

    def create_vector_configuration(
        self, project_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._post(
            f"/projects/{project_id}/vector/configurations",
            payload,
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def delete_vector_configuration(self, project_id: str, config_id: str) -> dict[str, Any]:
        return self._delete(f"/projects/{project_id}/vector/configurations/{config_id}")

    def set_default_vector_configuration(self, project_id: str, config_id: str) -> dict[str, Any]:
        return self._patch(
            f"/projects/{project_id}/vector/configurations/{config_id}",
            {"is_default": True},
        )

    def reindex_vector_configuration(self, project_id: str, config_id: str) -> dict[str, Any]:
        return self._post(
            f"/projects/{project_id}/vector/configurations/{config_id}/reindex",
            {},
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def list_text_configurations(self, project_id: str) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}/text/configurations")

    def create_text_configuration(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(
            f"/projects/{project_id}/text/configurations",
            payload,
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def delete_text_configuration(self, project_id: str, config_id: str) -> dict[str, Any]:
        return self._delete(f"/projects/{project_id}/text/configurations/{config_id}")

    def retrieval_readiness(self, project_id: str) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}/retrieval/readiness")

    def api_request(self, plan: ApiRequestPlan) -> Any:
        return self._request(
            plan.operation.method,
            plan.request_path,
            json=plan.body if plan.has_body else None,
            json_provided=plan.has_body,
            retry=plan.operation.method == "GET",
            extra_headers=plan.headers,
        )

    def context_capabilities(self, project_id: str) -> dict[str, Any]:
        return self._get(self._context_path(project_id, "/capabilities"))

    def context_onboarding(self, project_id: str) -> dict[str, Any]:
        return self._get(self._context_path(project_id, "/onboarding"))

    def context_onboarding_action(self, project_id: str, action: str) -> dict[str, Any]:
        if action not in {"evaluate", "refresh", "acknowledge", "dismiss"}:
            raise ValueError(f"Unsupported Context onboarding action: {action}")
        return self._post(
            self._context_path(project_id, f"/onboarding/{action}"),
            {},
            retry=True,
        )

    def context_discover(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/discover"), payload, retry=True)

    def context_preflight(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/preflight"), payload, retry=True)

    def context_collections_list(
        self, project_id: str, *, status: str | None, limit: int, cursor: str | None
    ) -> dict[str, Any]:
        return self._get(
            _query_path(
                self._context_path(project_id, "/collections"),
                {"status": status, "limit": limit, "cursor": cursor},
            )
        )

    def context_collections_get(self, project_id: str, collection_id: str) -> dict[str, Any]:
        return self._get(self._context_path(project_id, f"/collections/{collection_id}"))

    def context_collections_create(
        self, project_id: str, payload: dict[str, Any], *, idempotency_key: str
    ) -> dict[str, Any]:
        return self._post(
            self._context_path(project_id, "/collections"),
            payload,
            retry=True,
            idempotency_key=idempotency_key,
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def context_collections_status(
        self, project_id: str, collection_id: str
    ) -> dict[str, Any]:
        return self._get(self._context_path(project_id, f"/collections/{collection_id}/status"))

    def context_collections_verify(
        self, project_id: str, collection_id: str
    ) -> dict[str, Any]:
        return self._post(
            self._context_path(project_id, f"/collections/{collection_id}/verify"),
            {},
            retry=True,
        )

    def context_collections_update(
        self,
        project_id: str,
        collection_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._patch(
            self._context_path(project_id, f"/collections/{collection_id}"),
            payload,
            retry=True,
            idempotency_key=idempotency_key,
        )

    def context_collections_diagnostics(
        self, project_id: str, collection_id: str
    ) -> dict[str, Any]:
        return self._get(
            self._context_path(project_id, f"/collections/{collection_id}/diagnostics")
        )

    def context_collections_set_default(
        self, project_id: str, collection_id: str, *, idempotency_key: str
    ) -> dict[str, Any]:
        return self.context_collections_update(
            project_id,
            collection_id,
            {"is_default": True},
            idempotency_key=idempotency_key,
        )

    def context_collections_delete(
        self, project_id: str, collection_id: str, *, idempotency_key: str
    ) -> dict[str, Any]:
        return self._delete(
            self._context_path(project_id, f"/collections/{collection_id}"),
            payload={"confirm_collection_id": collection_id},
            retry=True,
            idempotency_key=idempotency_key,
        )

    def context_collections_reindex(
        self, project_id: str, collection_id: str, *, idempotency_key: str
    ) -> dict[str, Any]:
        return self._post(
            self._context_path(project_id, f"/collections/{collection_id}/reindex"),
            {},
            retry=True,
            idempotency_key=idempotency_key,
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def context_filters_list(self, project_id: str, collection_id: str) -> dict[str, Any]:
        return self._get(
            self._context_path(project_id, f"/collections/{collection_id}/filters")
        )

    def context_filters_add_column(
        self,
        project_id: str,
        collection_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            self._context_path(project_id, f"/collections/{collection_id}/filters/columns"),
            payload,
            retry=True,
            idempotency_key=idempotency_key,
        )

    def context_filters_add_jsonb_path(
        self,
        project_id: str,
        collection_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            self._context_path(
                project_id, f"/collections/{collection_id}/filters/jsonb-paths"
            ),
            payload,
            retry=True,
            idempotency_key=idempotency_key,
        )

    def context_points_upsert(
        self,
        project_id: str,
        collection_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            self._context_path(project_id, f"/collections/{collection_id}/points/upsert"),
            payload,
            retry=True,
            idempotency_key=idempotency_key,
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def context_points_delete(
        self,
        project_id: str,
        collection_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            self._context_path(project_id, f"/collections/{collection_id}/points/delete"),
            payload,
            retry=True,
            idempotency_key=idempotency_key,
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def context_points_status(self, project_id: str, collection_id: str) -> dict[str, Any]:
        return self._get(
            self._context_path(project_id, f"/collections/{collection_id}/points/status")
        )

    def context_points_reconcile(
        self, project_id: str, collection_id: str, *, idempotency_key: str
    ) -> dict[str, Any]:
        return self._post(
            self._context_path(project_id, f"/collections/{collection_id}/points/reconcile"),
            {},
            retry=True,
            idempotency_key=idempotency_key,
            timeout=HEAVY_REQUEST_TIMEOUT,
        )

    def context_points_scroll(
        self,
        project_id: str,
        collection_id: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        return self._get(
            _query_path(
                self._context_path(project_id, f"/collections/{collection_id}/points"),
                {"limit": limit, "cursor": cursor},
            )
        )

    def context_operations_list(
        self,
        project_id: str,
        *,
        collection_id: str | None,
        kind: str | None,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        return self._get(
            _query_path(
                self._context_path(project_id, "/operations"),
                {
                    "collection_id": collection_id,
                    "kind": kind,
                    "status": status,
                    "limit": limit,
                    "cursor": cursor,
                },
            )
        )

    def context_operations_get(
        self, project_id: str, operation_id: str, *, deadline: float | None = None
    ) -> dict[str, Any]:
        return self._get(
            self._context_path(project_id, f"/operations/{operation_id}"),
            deadline=deadline,
        )

    def context_operations_get_poll(
        self, project_id: str, operation_id: str, *, deadline: float | None = None
    ) -> ContextPollResponse:
        result = self._request(
            "GET",
            self._context_path(project_id, f"/operations/{operation_id}"),
            retry=True,
            deadline=deadline,
            poll_metadata=True,
        )
        assert isinstance(result, ContextPollResponse)
        return result

    def context_operations_cancel(
        self, project_id: str, operation_id: str, *, idempotency_key: str
    ) -> dict[str, Any]:
        return self._post(
            self._context_path(project_id, f"/operations/{operation_id}/cancel"),
            {},
            retry=True,
            idempotency_key=idempotency_key,
        )

    def context_operations_retry(
        self, project_id: str, operation_id: str, *, idempotency_key: str
    ) -> dict[str, Any]:
        return self._post(
            self._context_path(project_id, f"/operations/{operation_id}/retry"),
            {},
            retry=True,
            idempotency_key=idempotency_key,
        )

    def context_count(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/count"), payload, retry=True)

    def context_facets(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/facets"), payload, retry=True)

    def context_search(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/search"), payload)

    def context_grouped_search(
        self, project_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/grouped-search"), payload)

    def context_recall_check(
        self, project_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/recall-check"), payload)

    def context_text_hybrid(
        self, project_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/hybrid/text"), payload)

    def context_graph_first(
        self, project_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/hybrid/graph-first"), payload)

    def context_vector_first(
        self, project_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/hybrid/vector-first"), payload)

    def context_rank_fusion(
        self, project_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/hybrid/rank-fusion"), payload)

    def context_joint(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(self._context_path(project_id, "/hybrid/joint"), payload)

    @staticmethod
    def _context_path(project_id: str, suffix: str) -> str:
        return f"/projects/{project_id}/context{suffix}"

    def _get(self, path: str, *, deadline: float | None = None) -> dict[str, Any]:
        result = self._request("GET", path, retry=True, deadline=deadline)
        assert isinstance(result, dict)
        return result

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        auth: bool = True,
        retry: bool = False,
        timeout: float | None = None,
        deadline: float | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        result = self._request(
            "POST",
            path,
            json=payload,
            auth=auth,
            retry=retry,
            timeout=timeout,
            deadline=deadline,
            idempotency_key=idempotency_key,
        )
        assert isinstance(result, dict)
        return result

    def _put(
        self, path: str, payload: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        result = self._request("PUT", path, json=payload, retry=False, timeout=timeout)
        assert isinstance(result, dict)
        return result

    def _patch(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        retry: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        result = self._request(
            "PATCH",
            path,
            json=payload,
            retry=retry,
            idempotency_key=idempotency_key,
        )
        assert isinstance(result, dict)
        return result

    def _delete(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        retry: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        result = self._request(
            "DELETE",
            path,
            json=payload,
            retry=retry,
            idempotency_key=idempotency_key,
        )
        assert isinstance(result, dict)
        return result

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        json_provided: bool = False,
        auth: bool = True,
        retry: bool = False,
        allow_refresh: bool = True,
        timeout: float | None = None,
        deadline: float | None = None,
        idempotency_key: str | None = None,
        poll_metadata: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> Any | ContextPollResponse:
        if auth and not self._access_token:
            raise CliError("AUTH_REQUIRED", "Run `polygres login` to continue.", exit_code=3)
        headers = {"User-Agent": f"polygres-cli/{__version__}"}
        if auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        for name, value in (extra_headers or {}).items():
            if name.lower() in {
                "authorization",
                "connection",
                "content-length",
                "content-type",
                "cookie",
                "host",
                "proxy-authorization",
                "transfer-encoding",
                "user-agent",
            }:
                raise CliError(
                    "API_PARAMETER_INVALID",
                    f"Header parameter {name} cannot override CLI request headers.",
                    exit_code=2,
                )
            headers[name] = value
        url = f"{self._base_url}{path}"
        retry_budget = self._max_retries if retry else 0
        started = time.monotonic()
        response: httpx.Response | None = None
        for attempt in range(retry_budget + 1):
            remaining = _remaining_seconds(deadline)
            if remaining is not None and remaining <= 0:
                raise CliError(
                    "TIMEOUT",
                    "The command timed out. Retry with a larger --timeout value.",
                    exit_code=UNAVAILABLE,
                )
            try:
                request_kwargs: dict[str, Any] = {
                    "headers": headers,
                }
                if json is not None or json_provided:
                    headers["Content-Type"] = "application/json"
                    request_kwargs["content"] = jsonlib.dumps(json)
                request_timeout = timeout
                if remaining is not None:
                    request_timeout = min(request_timeout or self._timeout, remaining)
                if request_timeout is not None:
                    request_kwargs["timeout"] = request_timeout
                response = self._client.request(method, url, **request_kwargs)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < retry_budget:
                    _sleep_before_retry(attempt, None, deadline=deadline)
                    continue
                raise CliError(
                    "SERVICE_UNAVAILABLE",
                    f"Could not complete {method} {path} because the Polygres API "
                    "timed out or the network connection failed. Check the API URL, "
                    "network, and proxy settings, then retry.",
                    exit_code=UNAVAILABLE,
                ) from exc
            if response.status_code in RETRY_STATUSES:
                retry_payload = _json_payload(response)
                if is_maintenance_error_payload(retry_payload):
                    raise api_error_from_response(response.status_code, retry_payload)
                if attempt < retry_budget:
                    _sleep_before_retry(
                        attempt,
                        response.headers.get("Retry-After"),
                        deadline=deadline,
                    )
                    continue
            break
        assert response is not None
        elapsed_ms = int((time.monotonic() - started) * 1000)
        payload = _json_payload(response)
        if self._verbose:
            request_id = payload.get("request_id") if isinstance(payload, dict) else None
            self._emit_trace(method, path, response.status_code, elapsed_ms, request_id)
        if response.is_error:
            if (
                auth
                and allow_refresh
                and response.status_code == 401
                and self._refresh_token
                and self._refresh_access_token()
            ):
                return self._request(
                    method,
                    path,
                    json=json,
                    json_provided=json_provided,
                    auth=auth,
                    retry=retry,
                    allow_refresh=False,
                    timeout=timeout,
                    deadline=deadline,
                    idempotency_key=idempotency_key,
                    poll_metadata=poll_metadata,
                    extra_headers=extra_headers,
                )
            raise api_error_from_response(
                response.status_code,
                payload if isinstance(payload, dict) else None,
            )
        if poll_metadata:
            if not isinstance(payload, dict):
                raise CliError(
                    "API_RESPONSE_INVALID",
                    "Polygres API returned an invalid polling response.",
                )
            return ContextPollResponse(
                envelope=payload,
                retry_after_seconds=_retry_after_seconds(response.headers.get("Retry-After")),
            )
        return payload

    def _refresh_access_token(self) -> bool:
        if self._refresh_attempted or not self._refresh_token:
            return False
        self._refresh_attempted = True
        try:
            payload = self.refresh_login(self._refresh_token)
        except CliError as exc:
            if (
                exc.exit_code == AUTH or exc.code == "CLI_AUTH_RESPONSE_INVALID"
            ) and self._on_refresh_auth_failure is not None:
                self._on_refresh_auth_failure()
            raise
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            if self._on_refresh_auth_failure is not None:
                self._on_refresh_auth_failure()
            request_id = payload.get("request_id")
            raise CliError(
                "AUTH_REFRESH_INVALID",
                "The API returned an invalid token refresh response. Run `polygres login` "
                "to sign in again.",
                exit_code=AUTH,
                request_id=request_id if isinstance(request_id, str) else None,
            )
        self._access_token = access_token
        self._refresh_token = refresh_token
        if self._on_token_refresh is not None:
            self._on_token_refresh(payload)
        return True

    def _emit_trace(
        self, method: str, path: str, status: int, elapsed_ms: int, request_id: object
    ) -> None:
        if not self._trace:
            return
        parsed = urlsplit(path)
        rendered_path = parsed.path or path
        parts = [f"{method} {rendered_path} -> {status}", f"{elapsed_ms}ms"]
        if request_id:
            parts.append(f"request_id={request_id}")
        self._trace(redact_string(" ".join(parts)))


def _json_payload(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        payload = response.json()
    except jsonlib.JSONDecodeError:
        return {}
    return payload


def _query_path(path: str, values: dict[str, object | None]) -> str:
    query = urlencode([(key, str(value)) for key, value in values.items() if value is not None])
    return f"{path}?{query}" if query else path


def _sleep_before_retry(
    attempt: int, retry_after: str | None, *, deadline: float | None = None
) -> None:
    delay = _retry_after_seconds(retry_after)
    if delay is None:
        delay = min(2**attempt, 5)
    remaining = _remaining_seconds(deadline)
    if remaining is not None:
        delay = min(delay, max(remaining, 0.0))
    if delay > 0:
        time.sleep(delay)


def _remaining_seconds(deadline: float | None) -> float | None:
    return None if deadline is None else deadline - time.monotonic()


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return max(parsed.timestamp() - time.time(), 0.0)


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
