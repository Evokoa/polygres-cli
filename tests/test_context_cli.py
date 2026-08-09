from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from polygres_cli import cli

PROJECT_ID = "p0123456789abcdef0123456"
COLLECTION_ID = "123e4567-e89b-12d3-a456-426614174000"
OPERATION_ID = "223e4567-e89b-12d3-a456-426614174000"
API_BASE_URL = "https://api.example.test/v1"
ACCESS_TOKEN = "pcli_at_synthetic_context_token"
ROUTE_CTX = getattr(respx, "mo" + "ck")


def run_cli(
    args: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    token: str | None = ACCESS_TOKEN,
) -> tuple[int, str, str]:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("POLYGRES_API_BASE_URL", API_BASE_URL)
    if token is None:
        monkeypatch.delenv("POLYGRES_ACCESS_TOKEN", raising=False)
    else:
        monkeypatch.setenv("POLYGRES_ACCESS_TOKEN", token)
    result = cli.main(args)
    captured = capsys.readouterr()
    return result, captured.out, captured.err


def context_args(*args: str, json_output: bool = True) -> list[str]:
    result = ["--project", PROJECT_ID]
    if json_output:
        result.insert(0, "--json")
    return [*result, "context", *args]


def response(operation_status: str = "queued") -> dict[str, Any]:
    return {
        "request_id": "req_synthetic",
        "operation": {
            "id": OPERATION_ID,
            "collection_id": COLLECTION_ID,
            "kind": "collection_create",
            "status": operation_status,
            "stage": "queued" if operation_status == "queued" else "ready",
            "processed_units": 0,
            "total_units": None,
            "attempts": 0,
            "error": None,
            "created_at": "2026-07-29T00:00:00Z",
            "started_at": None,
            "finished_at": None,
            "updated_at": "2026-07-29T00:00:00Z",
        },
    }


def joint_response() -> dict[str, Any]:
    return {
        "request_id": "req_joint",
        "collection": {"id": COLLECTION_ID, "name": "docs"},
        "mode": "joint",
        "results": [
            {
                "point_id": 42,
                "source": {"schema": "public", "table": "articles", "id": "doc_1"},
                "rank": 1,
                "score": 0.016,
                "score_kind": "joint_weighted_rrf",
                "metric": None,
                "properties": {"title": "Current guidance"},
                "group_value": None,
                "group_rank": None,
                "introduced_by_graph": False,
                "baseline_rank": 2,
                "rank_lift": 1,
                "context": {"rank": 1, "score": 0.8, "metric": "cosine"},
                "lexical": {"rank": 3, "score": 0.5},
                "graph": {"rank": 2, "depth": 1, "relationships": []},
                "score_breakdown": {
                    "semantic": 0.01,
                    "lexical": 0.002,
                    "graph": 0.004,
                    "total": 0.016,
                },
                "future_result_field": {"preserved": True},
            }
        ],
        "fusion": {
            "method": "joint_weighted_rrf",
            "k": 60,
            "weights": {"semantic": 0.4, "lexical": 0.2, "graph": 0.4},
        },
        "trace": {
            "semantic_candidates": 10,
            "lexical_candidates": 8,
            "explicit_seeds": 1,
            "retrieval_seeds": 2,
            "retained_seeds": 3,
            "graph_candidates": 6,
            "combined_candidates": 15,
            "rescored_candidates": 12,
        },
        "warnings": [],
        "future_envelope_field": {"preserved": True},
    }


def test_context_help_registers_complete_tree_and_rejects_superseded_names(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rc, out, err = run_cli(["context", "--help"], capsys, monkeypatch, tmp_path)

    assert rc == 0
    assert err == ""
    for command in (
        "capabilities",
        "init",
        "sources",
        "collections",
        "filters",
        "points",
        "operations",
        "count",
        "facets",
        "search",
        "text-hybrid",
        "graph-first",
        "vector-first",
        "rank-fusion",
        "joint",
        "grouped-search",
        "recall-check",
    ):
        assert command in out
    for args in (
        ["context", "points", "backfill", COLLECTION_ID],
        ["context", "points", "sync", COLLECTION_ID],
    ):
        rc, _out, _err = run_cli(args, capsys, monkeypatch, tmp_path)
        assert rc == 2


@pytest.mark.parametrize(
    "command",
    [
        ["capabilities"],
        ["init"],
        ["sources", "discover"],
        ["sources", "preflight", "--file", "request.json"],
        ["collections", "list"],
        ["collections", "get", COLLECTION_ID],
        ["collections", "status", COLLECTION_ID],
        ["collections", "verify", COLLECTION_ID],
        [
            "collections",
            "create",
            "docs",
            "--source",
            "new-table",
            "--table",
            "docs",
            "--dimensions",
            "2",
        ],
        ["collections", "update", COLLECTION_ID, "--max-search-limit", "10"],
        ["collections", "set-default", COLLECTION_ID],
        ["collections", "diagnostics", COLLECTION_ID],
        ["collections", "reindex", COLLECTION_ID],
        ["collections", "delete", COLLECTION_ID, "--yes"],
        ["filters", "list", COLLECTION_ID],
        [
            "filters",
            "add-column",
            COLLECTION_ID,
            "--key",
            "tenant_id",
            "--column",
            "tenant_id",
        ],
        [
            "filters",
            "add-jsonb-path",
            COLLECTION_ID,
            "--key",
            "topic",
            "--column",
            "metadata",
            "--path",
            "topic",
        ],
        ["points", "upsert", COLLECTION_ID, "doc_1"],
        ["points", "delete", COLLECTION_ID, "doc_1"],
        ["points", "status", COLLECTION_ID],
        ["points", "reconcile", COLLECTION_ID],
        ["points", "scroll", COLLECTION_ID],
        ["operations", "list"],
        ["operations", "get", OPERATION_ID],
        ["operations", "wait", OPERATION_ID],
        ["operations", "cancel", OPERATION_ID],
        ["operations", "retry", OPERATION_ID],
        ["count", "docs"],
        ["facets", "docs", "status"],
        ["search", "docs", "--embedding-json", "[0.1]"],
        [
            "text-hybrid",
            "docs",
            "--embedding-json",
            "[0.1]",
            "--query",
            "query",
        ],
        [
            "graph-first",
            "docs",
            "--embedding-json",
            "[0.1]",
            "--start-schema",
            "public",
            "--start-table",
            "accounts",
            "--start-id",
            "acct_1",
        ],
        ["vector-first", "docs", "--embedding-json", "[0.1]"],
        [
            "rank-fusion",
            "docs",
            "--embedding-json",
            "[0.1]",
            "--start-schema",
            "public",
            "--start-table",
            "accounts",
            "--start-id",
            "acct_1",
        ],
        ["joint", "docs", "--embedding-json", "[0.1]"],
        [
            "grouped-search",
            "docs",
            "--embedding-json",
            "[0.1]",
            "--group-by",
            "tenant_id",
        ],
        ["recall-check", "docs", "--embedding-json", "[0.1]"],
    ],
)
def test_every_public_context_command_parses(command: list[str]) -> None:
    parsed = cli.build_parser().parse_args(["--project", PROJECT_ID, "context", *command])
    assert callable(parsed.func)


@ROUTE_CTX
def test_capabilities_uses_selected_project_auth_and_exact_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {
        "request_id": "req_capabilities",
        "contract_version": "context.v1",
        "product_status": "preview",
        "additive_field": {"preserved": True},
    }
    route = respx.get(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/capabilities").mock(
        return_value=httpx.Response(200, json=payload)
    )

    rc, out, err = run_cli(
        context_args("capabilities"),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert err == ""
    assert json.loads(out) == payload
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"


@ROUTE_CTX
def test_context_init_reuses_one_eligible_pgvector_column(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vector_configuration_id = "323e4567-e89b-12d3-a456-426614174000"
    onboarding = {
        "request_id": "req_onboarding",
        "status": "eligible",
        "compatibility_generation": 1,
        "candidates": [
            {
                "vector_configuration_id": vector_configuration_id,
                "name": "articles",
                "schema_name": "public",
                "table_name": "articles",
                "row_id_column": "id",
                "embedding_column": "embedding",
                "dimensions": 1536,
                "metric": "cosine",
                "is_default": True,
            }
        ],
        "offer_acknowledged": False,
        "selected_vector_configuration_id": None,
        "completed_collection_id": None,
        "evaluated_at": "2026-08-06T00:00:00Z",
        "updated_at": "2026-08-06T00:00:00Z",
    }
    evaluate = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/onboarding/evaluate").mock(
        return_value=httpx.Response(200, json=onboarding)
    )
    acknowledge = respx.post(
        f"{API_BASE_URL}/projects/{PROJECT_ID}/context/onboarding/acknowledge"
    ).mock(return_value=httpx.Response(200, json={**onboarding, "offer_acknowledged": True}))
    create = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/collections").mock(
        return_value=httpx.Response(202, json=response())
    )

    rc, out, err = run_cli(
        context_args("init", "--yes", "--no-wait"),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert err == ""
    assert json.loads(out)["operation"]["id"] == OPERATION_ID
    assert evaluate.called and acknowledge.called and create.called
    assert json.loads(create.calls[0].request.content) == {
        "name": "articles_context",
        "source": {
            "mode": "existing",
            "schema_name": "public",
            "table_name": "articles",
            "source_key_column": "id",
            "content_column": None,
            "metadata_column": None,
        },
        "vector": {
            "name": None,
            "column_name": "embedding",
            "dimensions": 1536,
            "metric": "cosine",
        },
        "text_column": None,
        "result_columns": [],
        "filter_columns": [],
        "jsonb_filter_paths": [],
        "index_kind": "hnsw",
        "max_search_limit": 1000,
    }


def test_context_requires_project_and_login(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rc, out, _err = run_cli(
        ["--json", "context", "capabilities"],
        capsys,
        monkeypatch,
        tmp_path,
    )
    assert rc == 2
    assert json.loads(out)["error"]["code"] == "PROJECT_REQUIRED"

    rc, out, _err = run_cli(
        context_args("capabilities"),
        capsys,
        monkeypatch,
        tmp_path,
        token=None,
    )
    assert rc == 3
    assert json.loads(out)["error"]["code"] == "AUTH_REQUIRED"


@ROUTE_CTX
def test_context_permission_error_preserves_request_id_and_exit_code(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    respx.get(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/capabilities").mock(
        return_value=httpx.Response(
            403,
            json={
                "request_id": "req_denied",
                "error": {
                    "code": "PERMISSION_DENIED",
                    "message": "Permission denied.",
                    "details": {"permission": "context:read"},
                },
            },
        )
    )

    rc, out, err = run_cli(
        context_args("capabilities"),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 4
    assert err == ""
    assert json.loads(out)["request_id"] == "req_denied"


@ROUTE_CTX
def test_idempotency_conflict_preserves_structured_error(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/collections").mock(
        return_value=httpx.Response(
            409,
            json={
                "request_id": "req_conflict",
                "error": {
                    "code": "CONTEXT_IDEMPOTENCY_CONFLICT",
                    "message": "Idempotency key was used for another request.",
                    "details": {"field": "Idempotency-Key"},
                },
            },
        )
    )

    rc, out, err = run_cli(
        context_args(
            "collections",
            "create",
            "docs",
            "--source",
            "new-table",
            "--table",
            "docs",
            "--dimensions",
            "2",
            "--idempotency-key",
            "reused-key",
            "--no-wait",
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 6
    assert err == ""
    payload = json.loads(out)
    assert payload["error"]["code"] == "CONTEXT_IDEMPOTENCY_CONFLICT"
    assert payload["request_id"] == "req_conflict"


@ROUTE_CTX
def test_create_serializes_defaults_and_idempotency_without_waiting(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    route = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/collections").mock(
        return_value=httpx.Response(202, json=response())
    )

    rc, out, err = run_cli(
        context_args(
            "collections",
            "create",
            "support_docs",
            "--source",
            "new-table",
            "--table",
            "support_docs",
            "--dimensions",
            "768",
            "--idempotency-key",
            "stable-synthetic-key",
            "--no-wait",
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert err == ""
    assert json.loads(out) == response()
    request = route.calls[0].request
    assert request.headers["Idempotency-Key"] == "stable-synthetic-key"
    body = json.loads(request.content)
    assert body["source"] == {
        "mode": "new_table",
        "schema_name": "public",
        "table_name": "support_docs",
        "source_key_column": "id",
        "content_column": "content",
        "metadata_column": "metadata",
    }
    assert body["vector"] == {
        "name": None,
        "column_name": "embedding",
        "dimensions": 768,
        "metric": "cosine",
    }


@pytest.mark.parametrize(
    "args",
    [
        ["collections", "get", "not-a-uuid"],
        ["collections", "update", COLLECTION_ID],
        [
            "collections",
            "update",
            COLLECTION_ID,
            "--clear-result-columns",
            "--result-column",
            "title",
        ],
        ["filters", "add-jsonb-path", COLLECTION_ID, "--key", "topic", "--column", "metadata"],
        ["points", "upsert", COLLECTION_ID, ""],
        ["search", "docs", "--embedding-json", "[true]"],
        [
            "search",
            "docs",
            "--embedding-json",
            "[0.1]",
            "--embedding-file",
            "embedding.json",
        ],
        [
            "rank-fusion",
            "docs",
            "--embedding-json",
            "[0.1]",
            "--start-schema",
            "public",
            "--start-table",
            "accounts",
            "--start-id",
            "acct_1",
            "--context-weight",
            "0",
            "--graph-weight",
            "0",
        ],
        [
            "joint",
            "docs",
            "--embedding-json",
            "[0.1]",
            "--lexical-weight",
            "0.1",
        ],
        [
            "joint",
            "docs",
            "--embedding-json",
            "[0.1]",
            "--start-json",
            "{}",
        ],
        [
            "joint",
            "docs",
            "--embedding-json",
            "[0.1]",
            "--semantic-weight",
            "0",
            "--lexical-weight",
            "0",
            "--graph-weight",
            "0",
        ],
        ["joint", "docs", "--embedding-json", "[0.1]", "--seed-limit", "33"],
        ["grouped-search", "docs", "--embedding-json", "[0.1]"],
    ],
)
def test_local_validation_fails_before_http(
    args: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rc, out, _err = run_cli(
        context_args(*args),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 2
    assert json.loads(out)["error"]["code"] in {
        "VALIDATION_ERROR",
        "CONTEXT_REQUEST_INVALID",
        "CONTEXT_POINT_KEY_INVALID",
        "CONTEXT_EMBEDDING_INVALID",
        "CONTEXT_RANKING_WEIGHTS_INVALID",
    }


def test_strict_file_and_stdin_input_rejects_duplicates_and_accepts_object(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"name":"one","name":"two"}', encoding="utf-8")

    rc, out, _err = run_cli(
        context_args("sources", "preflight", "--file", str(duplicate)),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 2
    assert json.loads(out)["error"]["code"] == "CONTEXT_REQUEST_FILE_INVALID"

    monkeypatch.setattr(cli.sys, "stdin", io.StringIO('{"unknown":true}'))
    rc, out, _err = run_cli(
        context_args("sources", "preflight", "--file", "-"),
        capsys,
        monkeypatch,
        tmp_path,
    )
    assert rc == 2
    assert json.loads(out)["error"]["code"] == "CONTEXT_REQUEST_INVALID"


@ROUTE_CTX
def test_create_request_embedding_filter_files_and_ranked_stdin(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_file = tmp_path / "create.json"
    create_file.write_text(
        json.dumps(
            {
                "source": {
                    "mode": "new_table",
                    "schema_name": "public",
                    "table_name": "docs",
                    "source_key_column": "id",
                    "content_column": "content",
                    "metadata_column": "metadata",
                },
                "vector": {
                    "column_name": "embedding",
                    "dimensions": 2,
                    "metric": "cosine",
                },
            }
        ),
        encoding="utf-8",
    )
    create_route = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/collections").mock(
        return_value=httpx.Response(202, json=response())
    )
    rc, out, err = run_cli(
        context_args(
            "collections",
            "create",
            "docs",
            "--file",
            str(create_file),
            "--no-wait",
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )
    assert rc == 0
    assert err == ""
    assert json.loads(out) == response()
    assert json.loads(create_route.calls[0].request.content)["name"] == "docs"
    generated_key = create_route.calls[0].request.headers["Idempotency-Key"]
    assert len(generated_key) == 36
    assert generated_key.count("-") == 4

    embedding_file = tmp_path / "embedding.json"
    embedding_file.write_text("[0.1,0.2]", encoding="utf-8")
    filter_file = tmp_path / "filter.json"
    filter_file.write_text(
        '{"must":[{"key":"tenant_id","match":"acme"}]}',
        encoding="utf-8",
    )
    ranked_payload = {
        "request_id": "req_ranked",
        "collection": {"id": COLLECTION_ID, "name": "docs"},
        "mode": "dense",
        "results": [],
        "warnings": [],
    }
    search_route = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/search").mock(
        return_value=httpx.Response(200, json=ranked_payload)
    )
    rc, out, err = run_cli(
        context_args(
            "search",
            "docs",
            "--embedding-file",
            str(embedding_file),
            "--filter-file",
            str(filter_file),
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )
    assert rc == 0
    assert err == ""
    assert json.loads(out) == ranked_payload
    search_body = json.loads(search_route.calls[-1].request.content)
    assert search_body["embedding"] == [0.1, 0.2]
    assert search_body["filter"]["must"][0]["key"] == "tenant_id"

    monkeypatch.setattr(cli.sys, "stdin", io.StringIO('{"embedding":[0.3,0.4]}'))
    rc, out, err = run_cli(
        context_args("search", "docs", "--request", "-"),
        capsys,
        monkeypatch,
        tmp_path,
    )
    assert rc == 0
    assert err == ""
    assert json.loads(out) == ranked_payload
    assert json.loads(search_route.calls[-1].request.content)["embedding"] == [0.3, 0.4]


@pytest.mark.parametrize(
    ("command", "endpoint", "mode", "expected"),
    [
        (
            ["search", "docs", "--embedding-json", "[0.1,0.2]"],
            "/context/search",
            "dense",
            {"limit": 10},
        ),
        (
            [
                "text-hybrid",
                "docs",
                "--embedding-json",
                "[0.1,0.2]",
                "--query",
                "reset password",
            ],
            "/context/hybrid/text",
            "text_hybrid",
            {"query": "reset password"},
        ),
        (
            [
                "graph-first",
                "docs",
                "--embedding-json",
                "[0.1,0.2]",
                "--start-schema",
                "public",
                "--start-table",
                "accounts",
                "--start-id",
                "acct_1",
                "--direction",
                "both",
            ],
            "/context/hybrid/graph-first",
            "graph_first",
            {"direction": "any"},
        ),
        (
            ["vector-first", "docs", "--embedding-json", "[0.1,0.2]"],
            "/context/hybrid/vector-first",
            "vector_first",
            {"context_limit": 50},
        ),
        (
            [
                "rank-fusion",
                "docs",
                "--embedding-json",
                "[0.1,0.2]",
                "--start-schema",
                "public",
                "--start-table",
                "accounts",
                "--start-id",
                "acct_1",
            ],
            "/context/hybrid/rank-fusion",
            "rank_fusion",
            {"weights": {"context": 0.7, "graph": 0.3}},
        ),
        (
            [
                "grouped-search",
                "docs",
                "--embedding-json",
                "[0.1,0.2]",
                "--group-by",
                "tenant_id",
            ],
            "/context/grouped-search",
            "dense",
            {"group_by": "tenant_id", "group_limit": 1},
        ),
    ],
)
@ROUTE_CTX
def test_every_ranked_mode_uses_context_wire_contract(
    command: list[str],
    endpoint: str,
    mode: str,
    expected: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {
        "request_id": "req_ranked",
        "collection": {"id": COLLECTION_ID, "name": "docs"},
        "mode": mode,
        "results": [],
        "warnings": [],
    }
    route = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}{endpoint}").mock(
        return_value=httpx.Response(200, json=payload)
    )

    rc, out, err = run_cli(
        context_args(*command),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert err == ""
    assert json.loads(out) == payload
    body = json.loads(route.calls[0].request.content)
    assert body["collection"] == "docs"
    assert body["embedding"] == [0.1, 0.2]
    for key, value in expected.items():
        assert body[key] == value
    assert "cursor" not in body
    assert "joint" not in json.dumps(body)


@ROUTE_CTX
def test_joint_uses_strict_context_route_and_preserves_json_response(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = joint_response()
    route = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/hybrid/joint").mock(
        return_value=httpx.Response(200, json=payload)
    )
    start = '{"schema":"public","table":"accounts","id":"acct_1"}'

    rc, out, err = run_cli(
        context_args(
            "joint",
            "docs",
            "--embedding-json",
            "[0.1,0.2]",
            "--query",
            "current guidance",
            "--start-json",
            start,
            "--start-json",
            start,
            "--filter-json",
            '{"must":[{"key":"tenant_id","match":"acme"}]}',
            "--relationship-type",
            "owns",
            "--relationship-type",
            "owns",
            "--direction",
            "both",
            "--max-depth",
            "3",
            "--context-limit",
            "40",
            "--seed-limit",
            "6",
            "--graph-limit",
            "150",
            "--traversal-limit",
            "400",
            "--semantic-weight",
            "0.4",
            "--lexical-weight",
            "0.2",
            "--graph-weight",
            "0.4",
            "--limit",
            "7",
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert err == ""
    assert json.loads(out) == payload
    assert len(respx.calls) == 1
    request = route.calls[0].request
    body = json.loads(request.content)
    assert body == {
        "collection": "docs",
        "vector_name": None,
        "embedding": [0.1, 0.2],
        "query": "current guidance",
        "starts": [{"schema": "public", "table": "accounts", "id": "acct_1"}],
        "filter": {"must": [{"key": "tenant_id", "match": "acme"}]},
        "relationship_types": ["owns"],
        "direction": "any",
        "max_depth": 3,
        "graph_limit": 150,
        "limit": 7,
        "context_limit": 40,
        "seed_limit": 6,
        "traversal_limit": 400,
        "weights": {"semantic": 0.4, "lexical": 0.2, "graph": 0.4},
    }
    assert request.url.path.endswith(f"/projects/{PROJECT_ID}/context/hybrid/joint")
    assert not request.url.path.endswith(f"/projects/{PROJECT_ID}/hybrid/joint")


@ROUTE_CTX
def test_joint_direct_flags_serialize_shared_defaults(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    route = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/hybrid/joint").mock(
        return_value=httpx.Response(200, json=joint_response())
    )

    rc, _out, err = run_cli(
        context_args("joint", "docs", "--embedding-json", "[0.1]"),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert err == ""
    assert json.loads(route.calls[0].request.content) == {
        "collection": "docs",
        "vector_name": None,
        "embedding": [0.1],
        "query": None,
        "starts": [],
        "filter": None,
        "relationship_types": [],
        "direction": "any",
        "max_depth": 2,
        "graph_limit": 200,
        "limit": 10,
        "context_limit": 50,
        "seed_limit": 8,
        "traversal_limit": 500,
        "weights": {"semantic": 0.7, "lexical": 0.0, "graph": 0.3},
    }


@ROUTE_CTX
def test_joint_request_file_is_authoritative_and_never_retries(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request_file = tmp_path / "joint.json"
    request_file.write_text(
        json.dumps(
            {
                "embedding": [0.1, 0.2],
                "query": "current guidance",
                "starts": [],
                "filter": None,
                "relationship_types": [],
                "direction": "both",
                "max_depth": 2,
                "context_limit": 50,
                "seed_limit": 8,
                "graph_limit": 200,
                "traversal_limit": 500,
                "weights": {"semantic": 0.4, "lexical": 0.2, "graph": 0.4},
                "limit": 10,
            }
        ),
        encoding="utf-8",
    )
    route = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/hybrid/joint").mock(
        return_value=httpx.Response(503, json={"error": {"code": "SERVICE_UNAVAILABLE"}})
    )

    rc, out, _err = run_cli(
        context_args("joint", "docs", "--request", str(request_file)),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 8
    assert json.loads(out)["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert route.call_count == 1
    body = json.loads(route.calls[0].request.content)
    assert body["collection"] == "docs"
    assert body["direction"] == "any"


@pytest.mark.parametrize("invalid", ["cursor", "response"])
@ROUTE_CTX
def test_joint_response_fails_closed(
    invalid: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = joint_response()
    if invalid == "cursor":
        payload["next_cursor"] = "forbidden"
    else:
        del payload["fusion"]
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/hybrid/joint").mock(
        return_value=httpx.Response(200, json=payload)
    )

    rc, out, _err = run_cli(
        context_args("joint", "docs", "--embedding-json", "[0.1]"),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 1
    error = json.loads(out)
    assert error["error"]["code"] == "CONTEXT_RESPONSE_INVALID"
    assert error["request_id"] == "req_joint"


@ROUTE_CTX
def test_recall_count_facets_and_filters(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases = [
        (
            ["count", "docs", "--filter-json", '{"must":[{"key":"tenant_id","match":"acme"}]}'],
            "/context/count",
            {"collection": "docs"},
            {"request_id": "req_count", "count": 2},
        ),
        (
            ["facets", "docs", "status"],
            "/context/facets",
            {"field": "status", "limit": 10},
            {"request_id": "req_facets", "facets": []},
        ),
        (
            ["recall-check", "docs", "--embedding-json", "[0.1,0.2]"],
            "/context/recall-check",
            {"minimum_recall": 0.95},
            {
                "request_id": "req_recall",
                "exact_count": 0,
                "candidate_count": 0,
                "intersection_count": 0,
                "recall": 1.0,
                "minimum_recall": 0.95,
                "status": "empty_exact",
            },
        ),
    ]
    for command, endpoint, expected, payload in cases:
        route = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}{endpoint}").mock(
            return_value=httpx.Response(200, json=payload)
        )
        rc, out, err = run_cli(
            context_args(*command),
            capsys,
            monkeypatch,
            tmp_path,
        )
        assert rc == 0
        assert err == ""
        assert json.loads(out) == payload
        body = json.loads(route.calls[-1].request.content)
        for key, value in expected.items():
            assert body[key] == value


@ROUTE_CTX
def test_ranked_human_output_precision_warnings_and_no_cursor(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {
        "request_id": "req_ranked",
        "collection": {"id": COLLECTION_ID, "name": "docs"},
        "mode": "rank_fusion",
        "results": [
            {
                "rank": 1,
                "source": {"schema": "public", "table": "articles", "id": "doc_1"},
                "score": 0.016237314597,
                "score_kind": "weighted_rrf",
                "context": {"rank": 1},
                "graph": {"rank": 3, "depth": 2},
            }
        ],
        "warnings": [
            {
                "code": "CONTEXT_GRAPH_CANDIDATES_UNMAPPED",
                "message": "Some candidates were unmapped.",
                "details": {"count": 3, "secret": "hidden"},
            }
        ],
    }
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/hybrid/rank-fusion").mock(
        return_value=httpx.Response(200, json=payload)
    )

    rc, out, err = run_cli(
        context_args(
            "rank-fusion",
            "docs",
            "--embedding-json",
            "[0.1,0.2]",
            "--start-schema",
            "public",
            "--start-table",
            "accounts",
            "--start-id",
            "acct_1",
            json_output=False,
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert err == ""
    assert "0.01623731" in out
    assert "public.articles:doc_1" in out
    assert "count=3" in out
    assert "secret" not in out
    assert "cursor" not in out.lower()


@pytest.mark.parametrize("cursor_field", ["cursor", "next_cursor", "has_more"])
@ROUTE_CTX
def test_ranked_cursor_response_fails_closed(
    cursor_field: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "request_id": "req_bad",
                "mode": "dense",
                "results": [],
                "warnings": [],
                cursor_field: True if cursor_field == "has_more" else "forbidden",
            },
        ),
    )

    rc, out, _err = run_cli(
        context_args("search", "docs", "--embedding-json", "[0.1]"),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 1
    assert json.loads(out)["error"]["code"] == "CONTEXT_RESPONSE_INVALID"


def test_noninteractive_delete_requires_yes_before_http(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rc, out, _err = run_cli(
        context_args("collections", "delete", COLLECTION_ID),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 2
    assert json.loads(out)["error"]["code"] == "CONTEXT_CONFIRMATION_REQUIRED"


@ROUTE_CTX
def test_interactive_delete_decline_fetches_plan_but_does_not_delete(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class TtyInput(io.StringIO):
        def isatty(self) -> bool:
            return True

    get_route = respx.get(
        f"{API_BASE_URL}/projects/{PROJECT_ID}/context/collections/{COLLECTION_ID}"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "request_id": "req_preview",
                "collection": {"id": COLLECTION_ID, "name": "docs"},
                "deletion_plan": {
                    "pgcontext_collection": "docs",
                    "drop_owned_index": "docs_embedding_hnsw",
                    "preserve_source_table": "public.docs",
                    "preserve_source_column": "embedding",
                    "preserve_indexes": ["user_index"],
                },
            },
        )
    )
    delete_route = respx.delete(
        f"{API_BASE_URL}/projects/{PROJECT_ID}/context/collections/{COLLECTION_ID}"
    ).mock(return_value=httpx.Response(202, json=response()))
    monkeypatch.setattr(cli.sys, "stdin", TtyInput("no\n"))

    rc, out, err = run_cli(
        context_args(
            "collections",
            "delete",
            COLLECTION_ID,
            json_output=False,
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert "Preserve source table" in out
    assert "Delete Context collection" in err
    assert get_route.called
    assert not delete_route.called


@pytest.mark.parametrize(
    ("command", "request_payload"),
    [
        (
            ["recall-check", "docs", "--minimum-recall", "0"],
            {"embedding": [0.1], "minimum_recall": 0.95},
        ),
        (
            ["rank-fusion", "docs", "--context-weight", "0"],
            {
                "embedding": [0.1],
                "start": {"schema": "public", "table": "accounts", "id": "acct_1"},
            },
        ),
        (
            ["text-hybrid", "docs", "--query", ""],
            {"embedding": [0.1], "query": "query"},
        ),
        (
            ["search", "docs", "--filter-json", ""],
            {"embedding": [0.1]},
        ),
        (
            ["joint", "docs", "--lexical-weight", "0"],
            {
                "embedding": [0.1],
                "weights": {"semantic": 0.7, "lexical": 0.0, "graph": 0.3},
            },
        ),
    ],
)
@ROUTE_CTX
def test_request_file_rejects_falsey_body_flags_before_http(
    command: list[str],
    request_payload: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request_payload), encoding="utf-8")

    rc, out, _err = run_cli(
        context_args(*command, "--request", str(request_file)),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 2
    assert json.loads(out)["error"]["code"] == "CONTEXT_REQUEST_INVALID"
    assert not respx.calls


@pytest.mark.parametrize(
    "command",
    [
        [
            "search",
            "docs",
            "--embedding-json",
            "",
            "--embedding-file",
            "embedding.json",
        ],
        [
            "count",
            "docs",
            "--filter-json",
            "",
            "--filter-file",
            "filter.json",
        ],
    ],
)
def test_mutually_exclusive_input_flags_reject_empty_values(
    command: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rc, out, _err = run_cli(
        context_args(*command),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 2
    assert json.loads(out)["error"]["code"] == "VALIDATION_ERROR"


@ROUTE_CTX
def test_ranked_human_output_escapes_terminal_control_characters_without_changing_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    unsafe_id = "doc_\x1b[31mred\x1b[0m\nnext"
    unsafe_warning = "Warning\x1b[2J\nnext"
    payload = {
        "request_id": "req_ranked",
        "collection": {"id": COLLECTION_ID, "name": "docs"},
        "mode": "dense",
        "results": [
            {
                "rank": 1,
                "source": {"schema": "public", "table": "articles", "id": unsafe_id},
                "score": 0.5,
                "score_kind": "context_metric",
            }
        ],
        "warnings": [
            {
                "code": "CONTEXT_WARNING",
                "message": unsafe_warning,
                "details": {"count": 1},
            }
        ],
    }
    route = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/search").mock(
        return_value=httpx.Response(200, json=payload)
    )

    rc, out, err = run_cli(
        context_args(
            "search",
            "docs",
            "--embedding-json",
            "[0.1]",
            json_output=False,
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert err == ""
    assert "\x1b" not in out
    assert "doc_\\x1b[31mred\\x1b[0m\\x0anext" in out
    assert "Warning\\x1b[2J\\x0anext" in out

    route.mock(return_value=httpx.Response(200, json=payload))
    rc, out, err = run_cli(
        context_args("search", "docs", "--embedding-json", "[0.1]"),
        capsys,
        monkeypatch,
        tmp_path,
    )
    assert rc == 0
    assert err == ""
    assert json.loads(out) == payload


@ROUTE_CTX
def test_capabilities_human_uses_server_message_and_verbose_machine_code(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {
        "request_id": "req_capabilities",
        "setup": False,
        "setup_blocker": "context_preview_disabled",
        "setup_blocker_message": "Context Preview is not enabled for this project.",
    }
    route = respx.get(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/capabilities").mock(
        return_value=httpx.Response(200, json=payload)
    )

    rc, out, err = run_cli(
        context_args("capabilities", json_output=False),
        capsys,
        monkeypatch,
        tmp_path,
    )
    assert rc == 0
    assert err == ""
    assert "Context Preview is not enabled for this project." in out
    assert "context_preview_disabled" not in out

    route.mock(return_value=httpx.Response(200, json=payload))
    rc, out, err = run_cli(
        [
            "--verbose",
            "--project",
            PROJECT_ID,
            "context",
            "capabilities",
        ],
        capsys,
        monkeypatch,
        tmp_path,
    )
    assert rc == 0
    assert err != ""
    assert "Context Preview is not enabled for this project." in out
    assert "Setup blocker" in out
    assert "context_preview_disabled" in out


@ROUTE_CTX
def test_manage_permission_error_preserves_scope_and_request_id(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/collections").mock(
        return_value=httpx.Response(
            403,
            json={
                "request_id": "req_manage_denied",
                "error": {
                    "code": "PERMISSION_DENIED",
                    "message": "Permission denied.",
                    "details": {"permission": "context:manage"},
                },
            },
        )
    )

    rc, out, err = run_cli(
        context_args(
            "collections",
            "create",
            "docs",
            "--source",
            "new-table",
            "--table",
            "docs",
            "--dimensions",
            "2",
            "--no-wait",
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 4
    assert err == ""
    rendered = json.loads(out)
    assert rendered["request_id"] == "req_manage_denied"
    assert rendered["error"]["code"] == "PERMISSION_DENIED"
    assert rendered["error"]["details"] == {}


@pytest.mark.parametrize(
    ("command", "method", "suffix", "payload"),
    [
        (
            ["collections", "list"],
            "GET",
            "/context/collections?limit=50",
            {"request_id": "req_list", "collections": [], "next_cursor": None, "has_more": False},
        ),
        (
            ["collections", "get", COLLECTION_ID],
            "GET",
            f"/context/collections/{COLLECTION_ID}",
            {
                "request_id": "req_get",
                "collection": {"id": COLLECTION_ID, "name": "docs"},
                "deletion_plan": {},
            },
        ),
        (
            ["collections", "status", COLLECTION_ID],
            "GET",
            f"/context/collections/{COLLECTION_ID}/status",
            {"request_id": "req_status", "collection_id": COLLECTION_ID, "status": "ready"},
        ),
        (
            ["collections", "verify", COLLECTION_ID],
            "POST",
            f"/context/collections/{COLLECTION_ID}/verify",
            {"request_id": "req_verify", "verified": False, "checks": []},
        ),
        (
            ["collections", "diagnostics", COLLECTION_ID],
            "GET",
            f"/context/collections/{COLLECTION_ID}/diagnostics",
            {"request_id": "req_diagnostics", "overall_status": "degraded", "checks": []},
        ),
        (
            ["filters", "list", COLLECTION_ID],
            "GET",
            f"/context/collections/{COLLECTION_ID}/filters",
            {"request_id": "req_filters", "collection_id": COLLECTION_ID, "filters": []},
        ),
        (
            ["points", "status", COLLECTION_ID],
            "GET",
            f"/context/collections/{COLLECTION_ID}/points/status",
            {"request_id": "req_points", "collection_id": COLLECTION_ID, "status": "current"},
        ),
        (
            ["points", "scroll", COLLECTION_ID],
            "GET",
            f"/context/collections/{COLLECTION_ID}/points?limit=50",
            {"request_id": "req_scroll", "points": [], "next_cursor": None, "has_more": False},
        ),
        (
            ["operations", "list"],
            "GET",
            "/context/operations?limit=50",
            {
                "request_id": "req_operations",
                "operations": [],
                "next_cursor": None,
                "has_more": False,
            },
        ),
        (
            ["operations", "get", OPERATION_ID],
            "GET",
            f"/context/operations/{OPERATION_ID}",
            response("succeeded"),
        ),
    ],
)
@ROUTE_CTX
def test_context_read_handlers_preserve_exact_json_envelopes(
    command: list[str],
    method: str,
    suffix: str,
    payload: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    route = respx.request(
        method,
        f"{API_BASE_URL}/projects/{PROJECT_ID}{suffix}",
    ).mock(return_value=httpx.Response(200, json=payload))

    rc, out, err = run_cli(
        context_args(*command),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert err == ""
    assert json.loads(out) == payload
    assert route.called


@pytest.mark.parametrize(
    ("command", "method", "suffix"),
    [
        (
            ["collections", "update", COLLECTION_ID, "--max-search-limit", "10"],
            "PATCH",
            f"/context/collections/{COLLECTION_ID}",
        ),
        (
            ["collections", "set-default", COLLECTION_ID],
            "PATCH",
            f"/context/collections/{COLLECTION_ID}",
        ),
        (
            ["collections", "reindex", COLLECTION_ID],
            "POST",
            f"/context/collections/{COLLECTION_ID}/reindex",
        ),
        (
            [
                "filters",
                "add-column",
                COLLECTION_ID,
                "--key",
                "tenant_id",
                "--column",
                "tenant_id",
            ],
            "POST",
            f"/context/collections/{COLLECTION_ID}/filters/columns",
        ),
        (
            [
                "filters",
                "add-jsonb-path",
                COLLECTION_ID,
                "--key",
                "topic",
                "--column",
                "metadata",
                "--path",
                "topic",
            ],
            "POST",
            f"/context/collections/{COLLECTION_ID}/filters/jsonb-paths",
        ),
        (
            ["points", "upsert", COLLECTION_ID, "doc_1"],
            "POST",
            f"/context/collections/{COLLECTION_ID}/points/upsert",
        ),
        (
            ["points", "delete", COLLECTION_ID, "doc_1"],
            "POST",
            f"/context/collections/{COLLECTION_ID}/points/delete",
        ),
        (
            ["points", "reconcile", COLLECTION_ID],
            "POST",
            f"/context/collections/{COLLECTION_ID}/points/reconcile",
        ),
        (
            ["operations", "cancel", OPERATION_ID],
            "POST",
            f"/context/operations/{OPERATION_ID}/cancel",
        ),
        (
            ["operations", "retry", OPERATION_ID],
            "POST",
            f"/context/operations/{OPERATION_ID}/retry",
        ),
    ],
)
@ROUTE_CTX
def test_durable_mutation_handlers_send_explicit_idempotency_and_no_wait(
    command: list[str],
    method: str,
    suffix: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = response()
    route = respx.request(
        method,
        f"{API_BASE_URL}/projects/{PROJECT_ID}{suffix}",
    ).mock(return_value=httpx.Response(202, json=payload))

    rc, out, err = run_cli(
        context_args(
            *command,
            "--idempotency-key",
            "stable-lifecycle-key",
            "--no-wait",
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert err == ""
    assert json.loads(out) == payload
    assert route.calls[0].request.headers["Idempotency-Key"] == "stable-lifecycle-key"


@ROUTE_CTX
def test_operation_wait_and_retry_follow_terminal_operation_envelopes(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    terminal = response("succeeded")
    get_route = respx.get(
        f"{API_BASE_URL}/projects/{PROJECT_ID}/context/operations/{OPERATION_ID}"
    ).mock(return_value=httpx.Response(200, json=terminal))

    rc, out, err = run_cli(
        context_args("operations", "wait", OPERATION_ID),
        capsys,
        monkeypatch,
        tmp_path,
    )
    assert rc == 0
    assert err == ""
    assert json.loads(out) == terminal
    assert get_route.call_count == 1

    new_operation_id = "323e4567-e89b-12d3-a456-426614174000"
    accepted = response()
    accepted["operation"]["id"] = new_operation_id
    terminal_retry = response("succeeded")
    terminal_retry["operation"]["id"] = new_operation_id
    respx.post(
        f"{API_BASE_URL}/projects/{PROJECT_ID}/context/operations/{OPERATION_ID}/retry"
    ).mock(return_value=httpx.Response(202, json=accepted))
    retry_get = respx.get(
        f"{API_BASE_URL}/projects/{PROJECT_ID}/context/operations/{new_operation_id}"
    ).mock(return_value=httpx.Response(200, json=terminal_retry))

    def wait_immediately(client, *, project_id, operation_id, **_kwargs):
        return client.context_operations_get(project_id, operation_id)

    monkeypatch.setattr(cli, "context_wait_for_operation", wait_immediately)
    rc, out, err = run_cli(
        context_args(
            "operations",
            "retry",
            OPERATION_ID,
            "--idempotency-key",
            "stable-retry-key",
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )
    assert rc == 0
    assert err == ""
    assert json.loads(out) == terminal_retry
    assert retry_get.call_count == 1


@pytest.mark.parametrize("action", ["cancel", "retry"])
@ROUTE_CTX
def test_lifecycle_conflict_is_a_nonretryable_structured_cli_error(
    action: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    route = respx.post(
        f"{API_BASE_URL}/projects/{PROJECT_ID}/context/operations/{OPERATION_ID}/{action}"
    ).mock(
        return_value=httpx.Response(
            409,
            json={
                "request_id": "req_lifecycle_conflict",
                "error": {
                    "code": "CONTEXT_OPERATION_STATE_CONFLICT",
                    "message": "The operation state does not allow this action.",
                    "details": {"status": "succeeded"},
                },
            },
        )
    )

    rc, out, err = run_cli(
        context_args(
            "operations",
            action,
            OPERATION_ID,
            "--idempotency-key",
            "stable-lifecycle-key",
            "--no-wait",
        ),
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 6
    assert err == ""
    assert route.call_count == 1
    assert route.calls[0].request.headers["Idempotency-Key"] == "stable-lifecycle-key"
    rendered = json.loads(out)
    assert rendered["request_id"] == "req_lifecycle_conflict"
    assert rendered["error"] == {
        "code": "CONTEXT_OPERATION_STATE_CONFLICT",
        "message": "The operation state does not allow this action.",
        "details": {"status": "succeeded"},
    }
