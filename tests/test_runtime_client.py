from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from polygres_cli._vendor.polygres_lib.errors import catalog_message
from polygres_cli.cli_errors import CliError, api_error_from_response
from polygres_cli.runtime_client import RuntimeClient, validate_runtime_api_url

PROJECT_ID = "p0123456789abcdef0123456"
RUNTIME_URL = f"https://{PROJECT_ID}.api.db.polygres.com/v1"
STAGING_RUNTIME_URL = f"https://{PROJECT_ID}.api.staging.db.polygres.com/v1"


def _grant(
    scope: str,
    token: str = "runtime-token",
    *,
    runtime_url: str = RUNTIME_URL,
) -> dict[str, str]:
    return {
        "request_id": "req_grant",
        "project_id": PROJECT_ID,
        "runtime_api_url": runtime_url,
        "access_token": token,
        "scope": scope,
        "expires_at": "2026-07-22T00:05:00Z",
    }


def test_runtime_client_keeps_control_and_runtime_credentials_isolated() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"request_id": "req_ok", "status": {}})

    grants: list[tuple[str, str]] = []

    def grant_provider(project_id: str, scope: str) -> dict[str, str]:
        grants.append((project_id, scope))
        return _grant(scope)

    client = RuntimeClient(
        grant_provider=grant_provider,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
    )

    client.get(PROJECT_ID, "graph:read", "/graph/status")
    client.get(PROJECT_ID, "graph:read", "/graph/status")

    assert grants == [(PROJECT_ID, "graph:read")]
    assert len(seen) == 2
    assert all(request.headers["authorization"] == "Bearer runtime-token" for request in seen)
    assert all("pcli_at_" not in str(request.headers) for request in seen)


def test_runtime_client_refreshes_once_on_401_but_does_not_replay_network_mutation() -> None:
    tokens = iter(("runtime-old", "runtime-new"))
    grants = 0

    def grant_provider(project_id: str, scope: str) -> dict[str, str]:
        nonlocal grants
        grants += 1
        return _grant(scope, next(tokens))

    statuses = iter((401, 200))

    def auth_handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(
            status,
            json=(
                {"error": {"code": "TOKEN_EXPIRED", "message": "expired"}}
                if status == 401
                else {"request_id": "req_ok"}
            ),
        )

    client = RuntimeClient(
        grant_provider=grant_provider,
        http_client=httpx.Client(transport=httpx.MockTransport(auth_handler)),
        now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    assert client.get(PROJECT_ID, "graph:read", "/graph/status")["request_id"] == "req_ok"
    assert grants == 2

    calls = 0

    def lost_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("response lost", request=request)

    mutation = RuntimeClient(
        grant_provider=lambda project_id, scope: _grant(scope),
        http_client=httpx.Client(transport=httpx.MockTransport(lost_handler)),
        now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    with pytest.raises(httpx.ReadTimeout):
        mutation.request(
            PROJECT_ID,
            "graph:manage",
            "POST",
            "/graph/build",
            json={"concurrent": False},
        )


def test_runtime_client_does_not_replay_write_after_401() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            401,
            json={"error": {"code": "TOKEN_EXPIRED", "message": "expired"}},
        )

    client = RuntimeClient(
        grant_provider=lambda project_id, scope: _grant(scope),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    with pytest.raises(CliError) as caught:
        client.request(
            PROJECT_ID,
            "rows:write",
            "POST",
            "/tables/public/items/rows",
            json={"row": {"id": 1}},
            allow_auth_replay=False,
        )
    assert caught.value.code == "TOKEN_EXPIRED"
    assert calls == 1
    assert calls == 1


def test_runtime_client_does_not_retry_maintenance_response() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            json={
                "request_id": "req_maintenance",
                "error": {
                    "code": "MAINTENANCE_READ_ONLY",
                    "message": "Changes are temporarily paused.",
                    "details": {"mode": "read_only"},
                },
            },
        )

    client = RuntimeClient(
        grant_provider=lambda project_id, scope: _grant(scope),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
        max_retries=2,
    )

    with pytest.raises(CliError) as exc:
        client.get(PROJECT_ID, "graph:read", "/graph/status")

    assert calls == 1
    assert getattr(exc.value, "code", None) == "MAINTENANCE_READ_ONLY"
    assert str(exc.value) == catalog_message("MAINTENANCE_READ_ONLY")


@pytest.mark.parametrize("variant", ["unique", "exclusion"])
def test_constraint_conflict_variants_use_conflict_exit_code(variant: str) -> None:
    error = api_error_from_response(
        409,
        {
            "request_id": "req_conflict",
            "error": {"code": "ROW_CONSTRAINT_VIOLATION", "variant": variant},
        },
    )

    assert error.exit_code == 6
    assert error.status_code == 409


def test_constraint_validation_variant_keeps_usage_exit_code() -> None:
    error = api_error_from_response(
        400,
        {
            "request_id": "req_check",
            "error": {"code": "ROW_CONSTRAINT_VIOLATION", "variant": "check"},
        },
    )

    assert error.exit_code == 2
    assert error.status_code == 400


@pytest.mark.parametrize("runtime_url", [RUNTIME_URL, STAGING_RUNTIME_URL])
def test_runtime_client_accepts_managed_runtime_environments(runtime_url: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"request_id": "req_ok"})

    client = RuntimeClient(
        grant_provider=lambda project_id, scope: _grant(scope, runtime_url=runtime_url),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
    )

    assert client.get(PROJECT_ID, "graph:read", "/graph/status") == {
        "request_id": "req_ok"
    }
    assert [str(request.url) for request in seen] == [f"{runtime_url}/graph/status"]


def test_runtime_client_maps_invalid_grant_url_to_typed_error() -> None:
    runtime_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal runtime_calls
        runtime_calls += 1
        return httpx.Response(200, json={"request_id": "req_unexpected"})

    client = RuntimeClient(
        grant_provider=lambda project_id, scope: _grant(
            scope,
            runtime_url=f"https://{PROJECT_ID}.attacker.example/v1",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
    )

    with pytest.raises(CliError) as caught:
        client.get(PROJECT_ID, "graph:read", "/graph/status")

    assert caught.value.code == "RUNTIME_GRANT_INVALID"
    assert caught.value.exit_code == 8
    assert caught.value.request_id == "req_grant"
    assert runtime_calls == 0


@pytest.mark.parametrize(
    "runtime_url",
    [
        "http://localhost:8000/v1",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_runtime_url_validation_allows_explicit_loopback_http(runtime_url: str) -> None:
    assert validate_runtime_api_url(
        runtime_url,
        PROJECT_ID,
        allow_local_http=True,
    ) == runtime_url


def test_runtime_url_validation_rejects_loopback_http_without_explicit_opt_in() -> None:
    with pytest.raises(ValueError):
        validate_runtime_api_url("http://localhost:8000/v1", PROJECT_ID)


@pytest.mark.parametrize(
    "value",
    [
        "http://p0123456789abcdef0123456.api.db.polygres.com/v1",
        "https://user:pass@p0123456789abcdef0123456.api.db.polygres.com/v1",
        "https://p0123456789abcdef0123456.api.db.polygres.com:443/v1",
        "https://p11111111111111111111111.api.db.polygres.com/v1",
        "https://p11111111111111111111111.api.staging.db.polygres.com/v1",
        "https://p0123456789abcdef0123456.api.staging.db.polygres.com.attacker.example/v1",
        f"{RUNTIME_URL}?token=x",
        f"{RUNTIME_URL}#fragment",
        f"{RUNTIME_URL}/graph",
    ],
)
def test_runtime_url_validation_rejects_untrusted_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_runtime_api_url(value, PROJECT_ID)
