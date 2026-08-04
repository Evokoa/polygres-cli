from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from polygres_cli.cli_errors import CliError
from polygres_cli.runtime_client import RuntimeClient, validate_runtime_api_url

PROJECT_ID = "p0123456789abcdef0123456"
RUNTIME_URL = f"https://{PROJECT_ID}.api.db.polygres.com/v1"


def _grant(scope: str, token: str = "runtime-token") -> dict[str, str]:
    return {
        "request_id": "req_grant",
        "project_id": PROJECT_ID,
        "runtime_api_url": RUNTIME_URL,
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
        now=lambda: datetime(2026, 7, 22, tzinfo=UTC),
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
        now=lambda: datetime(2026, 7, 22, tzinfo=UTC),
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
        now=lambda: datetime(2026, 7, 22, tzinfo=UTC),
    )
    with pytest.raises(httpx.ReadTimeout):
        mutation.request(
            PROJECT_ID,
            "graph:manage",
            "POST",
            "/graph/build",
            json={"concurrent": False},
        )
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
        now=lambda: datetime(2026, 7, 22, tzinfo=UTC),
        max_retries=2,
    )

    with pytest.raises(CliError) as exc:
        client.get(PROJECT_ID, "graph:read", "/graph/status")

    assert calls == 1
    assert getattr(exc.value, "code", None) == "MAINTENANCE_READ_ONLY"
    assert str(exc.value) == "Changes are temporarily paused."


@pytest.mark.parametrize(
    "value",
    [
        "http://p0123456789abcdef0123456.api.db.polygres.com/v1",
        "https://user:pass@p0123456789abcdef0123456.api.db.polygres.com/v1",
        "https://p11111111111111111111111.api.db.polygres.com/v1",
        f"{RUNTIME_URL}?token=x",
        f"{RUNTIME_URL}#fragment",
        f"{RUNTIME_URL}/graph",
    ],
)
def test_runtime_url_validation_rejects_untrusted_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_runtime_api_url(value, PROJECT_ID)
