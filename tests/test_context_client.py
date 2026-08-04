from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from polygres_cli.cli_client import CliControlPlaneClient, ContextPollResponse
from polygres_cli.cli_errors import CliError

API_BASE_URL = "https://api.example.test/v1"
ACCESS_TOKEN = "pcli_at_synthetic_context_token"
PROJECT_ID = "p0123456789abcdef0123456"
COLLECTION_ID = "123e4567-e89b-12d3-a456-426614174000"
OPERATION_ID = "223e4567-e89b-12d3-a456-426614174000"
IDEMPOTENCY_KEY = "synthetic-context-idempotency"


def test_every_context_client_method_uses_project_gateway_route_and_headers() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"request_id": "req_synthetic"},
            headers={"Retry-After": "3"},
        )

    client = CliControlPlaneClient(base_url=API_BASE_URL, access_token=ACCESS_TOKEN)
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(respond))

    calls: list[tuple[str, str, bool, Callable[[], object]]] = [
        ("GET", "/context/capabilities", False, lambda: client.context_capabilities(PROJECT_ID)),
        ("POST", "/context/discover", False, lambda: client.context_discover(PROJECT_ID, {})),
        ("POST", "/context/preflight", False, lambda: client.context_preflight(PROJECT_ID, {})),
        (
            "GET",
            "/context/collections?status=ready&limit=50&cursor=cursor",
            False,
            lambda: client.context_collections_list(
                PROJECT_ID, status="ready", limit=50, cursor="cursor"
            ),
        ),
        (
            "GET",
            f"/context/collections/{COLLECTION_ID}",
            False,
            lambda: client.context_collections_get(PROJECT_ID, COLLECTION_ID),
        ),
        (
            "POST",
            "/context/collections",
            True,
            lambda: client.context_collections_create(
                PROJECT_ID, {}, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        (
            "GET",
            f"/context/collections/{COLLECTION_ID}/status",
            False,
            lambda: client.context_collections_status(PROJECT_ID, COLLECTION_ID),
        ),
        (
            "POST",
            f"/context/collections/{COLLECTION_ID}/verify",
            False,
            lambda: client.context_collections_verify(PROJECT_ID, COLLECTION_ID),
        ),
        (
            "PATCH",
            f"/context/collections/{COLLECTION_ID}",
            True,
            lambda: client.context_collections_update(
                PROJECT_ID,
                COLLECTION_ID,
                {"max_search_limit": 10},
                idempotency_key=IDEMPOTENCY_KEY,
            ),
        ),
        (
            "GET",
            f"/context/collections/{COLLECTION_ID}/diagnostics",
            False,
            lambda: client.context_collections_diagnostics(PROJECT_ID, COLLECTION_ID),
        ),
        (
            "PATCH",
            f"/context/collections/{COLLECTION_ID}",
            True,
            lambda: client.context_collections_set_default(
                PROJECT_ID, COLLECTION_ID, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        (
            "DELETE",
            f"/context/collections/{COLLECTION_ID}",
            True,
            lambda: client.context_collections_delete(
                PROJECT_ID, COLLECTION_ID, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        (
            "POST",
            f"/context/collections/{COLLECTION_ID}/reindex",
            True,
            lambda: client.context_collections_reindex(
                PROJECT_ID, COLLECTION_ID, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        (
            "GET",
            f"/context/collections/{COLLECTION_ID}/filters",
            False,
            lambda: client.context_filters_list(PROJECT_ID, COLLECTION_ID),
        ),
        (
            "POST",
            f"/context/collections/{COLLECTION_ID}/filters/columns",
            True,
            lambda: client.context_filters_add_column(
                PROJECT_ID, COLLECTION_ID, {}, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        (
            "POST",
            f"/context/collections/{COLLECTION_ID}/filters/jsonb-paths",
            True,
            lambda: client.context_filters_add_jsonb_path(
                PROJECT_ID, COLLECTION_ID, {}, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        (
            "POST",
            f"/context/collections/{COLLECTION_ID}/points/upsert",
            True,
            lambda: client.context_points_upsert(
                PROJECT_ID, COLLECTION_ID, {}, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        (
            "POST",
            f"/context/collections/{COLLECTION_ID}/points/delete",
            True,
            lambda: client.context_points_delete(
                PROJECT_ID, COLLECTION_ID, {}, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        (
            "GET",
            f"/context/collections/{COLLECTION_ID}/points/status",
            False,
            lambda: client.context_points_status(PROJECT_ID, COLLECTION_ID),
        ),
        (
            "POST",
            f"/context/collections/{COLLECTION_ID}/points/reconcile",
            True,
            lambda: client.context_points_reconcile(
                PROJECT_ID, COLLECTION_ID, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        (
            "GET",
            f"/context/collections/{COLLECTION_ID}/points?limit=50&cursor=cursor",
            False,
            lambda: client.context_points_scroll(
                PROJECT_ID, COLLECTION_ID, limit=50, cursor="cursor"
            ),
        ),
        (
            "GET",
            (
                f"/context/operations?collection_id={COLLECTION_ID}"
                "&kind=points_reconcile&status=running&limit=50&cursor=cursor"
            ),
            False,
            lambda: client.context_operations_list(
                PROJECT_ID,
                collection_id=COLLECTION_ID,
                kind="points_reconcile",
                status="running",
                limit=50,
                cursor="cursor",
            ),
        ),
        (
            "GET",
            f"/context/operations/{OPERATION_ID}",
            False,
            lambda: client.context_operations_get(PROJECT_ID, OPERATION_ID),
        ),
        (
            "GET",
            f"/context/operations/{OPERATION_ID}",
            False,
            lambda: client.context_operations_get_poll(PROJECT_ID, OPERATION_ID),
        ),
        (
            "POST",
            f"/context/operations/{OPERATION_ID}/cancel",
            True,
            lambda: client.context_operations_cancel(
                PROJECT_ID, OPERATION_ID, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        (
            "POST",
            f"/context/operations/{OPERATION_ID}/retry",
            True,
            lambda: client.context_operations_retry(
                PROJECT_ID, OPERATION_ID, idempotency_key=IDEMPOTENCY_KEY
            ),
        ),
        ("POST", "/context/count", False, lambda: client.context_count(PROJECT_ID, {})),
        ("POST", "/context/facets", False, lambda: client.context_facets(PROJECT_ID, {})),
        ("POST", "/context/search", False, lambda: client.context_search(PROJECT_ID, {})),
        (
            "POST",
            "/context/grouped-search",
            False,
            lambda: client.context_grouped_search(PROJECT_ID, {}),
        ),
        (
            "POST",
            "/context/recall-check",
            False,
            lambda: client.context_recall_check(PROJECT_ID, {}),
        ),
        (
            "POST",
            "/context/hybrid/text",
            False,
            lambda: client.context_text_hybrid(PROJECT_ID, {}),
        ),
        (
            "POST",
            "/context/hybrid/graph-first",
            False,
            lambda: client.context_graph_first(PROJECT_ID, {}),
        ),
        (
            "POST",
            "/context/hybrid/vector-first",
            False,
            lambda: client.context_vector_first(PROJECT_ID, {}),
        ),
        (
            "POST",
            "/context/hybrid/rank-fusion",
            False,
            lambda: client.context_rank_fusion(PROJECT_ID, {}),
        ),
        (
            "POST",
            "/context/hybrid/joint",
            False,
            lambda: client.context_joint(PROJECT_ID, {}),
        ),
    ]

    results: list[object] = []
    try:
        for _method, _suffix, _mutation, invoke in calls:
            results.append(invoke())
    finally:
        client.close()

    assert len(requests) == len(calls)
    for request, (method, suffix, mutation, _invoke) in zip(requests, calls, strict=True):
        assert request.method == method
        assert str(request.url) == f"{API_BASE_URL}/projects/{PROJECT_ID}{suffix}"
        assert request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
        if mutation:
            assert request.headers["Idempotency-Key"] == IDEMPOTENCY_KEY
        else:
            assert "Idempotency-Key" not in request.headers
        assert f"/projects/{PROJECT_ID}/context/" in str(request.url)
        assert "/vector/" not in str(request.url)
        assert f"/projects/{PROJECT_ID}/hybrid/joint" not in str(request.url)

    delete_request = next(request for request in requests if request.method == "DELETE")
    assert json.loads(delete_request.content) == {"confirm_collection_id": COLLECTION_ID}
    poll_result = results[23]
    assert isinstance(poll_result, ContextPollResponse)
    assert poll_result.retry_after_seconds == 3


@pytest.mark.parametrize(
    ("method_name", "retry_expected"),
    [
        ("context_discover", True),
        ("context_search", False),
        ("context_grouped_search", False),
        ("context_recall_check", False),
        ("context_joint", False),
    ],
)
def test_context_post_retry_policy(
    method_name: str,
    retry_expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"error": {"code": "SERVICE_UNAVAILABLE"}})

    monkeypatch.setattr("polygres_cli.cli_client.time.sleep", lambda _seconds: None)
    client = CliControlPlaneClient(
        base_url=API_BASE_URL,
        access_token=ACCESS_TOKEN,
        max_retries=1,
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(respond))

    try:
        with pytest.raises(CliError):
            getattr(client, method_name)(PROJECT_ID, {})
    finally:
        client.close()

    assert attempts == (2 if retry_expected else 1)


def test_context_mutation_retry_reuses_exact_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"error": {"code": "SERVICE_UNAVAILABLE"}})
        return httpx.Response(202, json={"request_id": "req_retry", "operation": {}})

    monkeypatch.setattr("polygres_cli.cli_client.time.sleep", lambda _seconds: None)
    client = CliControlPlaneClient(
        base_url=API_BASE_URL,
        access_token=ACCESS_TOKEN,
        max_retries=1,
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(respond))

    try:
        client.context_collections_create(
            PROJECT_ID,
            {"name": "synthetic"},
            idempotency_key=IDEMPOTENCY_KEY,
        )
    finally:
        client.close()

    assert len(requests) == 2
    assert {request.headers["Idempotency-Key"] for request in requests} == {IDEMPOTENCY_KEY}
    assert requests[0].content == requests[1].content
