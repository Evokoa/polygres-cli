import io
import json

import httpx
import pytest
import respx
from test_context_cli import (
    API_BASE_URL,
    COLLECTION_ID,
    PROJECT_ID,
    context_args,
    joint_response,
    run_cli,
)


@pytest.mark.parametrize(
    "command,suffix,extra",
    [
        ("search", "search", []),
        ("grouped-search", "grouped-search", ["--group-by", "category"]),
        ("text-hybrid", "hybrid/text", ["--query", "lexical query"]),
        (
            "graph-first",
            "hybrid/graph-first",
            ["--start-schema", "public", "--start-table", "docs", "--start-id", "1"],
        ),
        ("vector-first", "hybrid/vector-first", []),
        (
            "rank-fusion",
            "hybrid/rank-fusion",
            ["--start-schema", "public", "--start-table", "docs", "--start-id", "1"],
        ),
        ("joint", "hybrid/joint", ["--query", "lexical query"]),
    ],
)
def test_text_preserves_endpoint_and_output(command, suffix, extra, capsys, monkeypatch, tmp_path):
    response = (
        joint_response()
        if command == "joint"
        else {
            "request_id": "query-test",
            "collection": {"id": COLLECTION_ID, "name": "docs"},
            "mode": "dense",
            "results": [],
            "warnings": [],
        }
    )
    with respx.mock as transport:
        route = transport.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/{suffix}").respond(
            200, json=response
        )
        rc, out, err = run_cli(
            context_args(
                command,
                "docs",
                "--text",
                "semantic query",
                "--vector-name",
                "content",
                "--idempotency-key",
                "query-1",
                *extra,
            ),
            capsys,
            monkeypatch,
            tmp_path,
        )
    assert rc == 0, err
    assert json.loads(out) == response
    payload = json.loads(route.calls[0].request.content)
    assert payload["text"] == "semantic query"
    assert payload["vector_name"] == "content"
    assert payload["use_credits"] is False
    assert "embedding" not in payload
    assert route.calls[0].request.headers["Idempotency-Key"] == "query-1"
    if command in {"joint", "text-hybrid"}:
        assert payload["query"] == "lexical query"


@pytest.mark.parametrize("source", ["file", "stdin", "request", "hybrid"])
def test_text_sources_and_query_fallback(source, capsys, monkeypatch, tmp_path):
    query = "replication question"
    suffix = "hybrid/text" if source == "hybrid" else "search"
    if source == "file":
        path = tmp_path / "query.txt"
        path.write_text(query)
        args = ["search", "docs", "--text-file", str(path)]
    elif source == "stdin":
        monkeypatch.setattr("sys.stdin", io.StringIO(query))
        args = ["search", "docs", "--text-file", "-"]
    elif source == "request":
        monkeypatch.setattr(
            "sys.stdin", io.StringIO(json.dumps({"text": query, "use_credits": True}))
        )
        args = ["search", "docs", "--request", "-"]
    else:
        args = ["text-hybrid", "docs", "--query", query]
    with respx.mock as transport:
        route = transport.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/{suffix}").respond(
            200, json={"results": []}
        )
        rc, _, err = run_cli(context_args(*args), capsys, monkeypatch, tmp_path)
    assert rc == 0, err
    body = json.loads(route.calls[0].request.content)
    assert body["text"] == query
    assert body["use_credits"] is (source == "request")
    assert route.calls[0].request.headers["Idempotency-Key"]


@pytest.mark.parametrize(
    "flags",
    [
        ["--text", " "],
        ["--text", "hello", "--embedding-json", "[0.1]"],
        ["--embedding-json", "[0.1]", "--use-credits"],
        ["--embedding-json", "[0.1]", "--idempotency-key", "key"],
        ["--text-file", "/does-not-exist/query.txt"],
        ["--request", "-", "--text", "hello"],
        ["--text", "hello", "--vector-name", "bad name"],
        ["--text", "hello", "--timeout", "0"],
    ],
)
def test_invalid_inputs_do_not_send_requests(flags, capsys, monkeypatch, tmp_path):
    with respx.mock as transport:
        rc, _, _ = run_cli(context_args("search", "docs", *flags), capsys, monkeypatch, tmp_path)
        assert rc == 2
        assert not transport.calls


def test_text_retries_reuse_key_and_timeout(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr("polygres_cli.cli_client._sleep_before_retry", lambda *args, **kwargs: None)
    with respx.mock as transport:
        route = transport.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/search").mock(
            side_effect=[
                httpx.Response(
                    503,
                    json={"error": {"code": "EMBEDDING_SERVICE_UNAVAILABLE", "message": "Retry"}},
                ),
                httpx.Response(200, json={"results": []}),
            ]
        )
        rc, _, err = run_cli(
            context_args("search", "docs", "--text", "hello", "--use-credits", "--timeout", "75"),
            capsys,
            monkeypatch,
            tmp_path,
        )
    assert rc == 0, err
    assert len(route.calls) == 2
    assert len({c.request.headers["Idempotency-Key"] for c in route.calls}) == 1
    for call in route.calls:
        assert json.loads(call.request.content)["use_credits"] is True
        assert 0 < call.request.extensions["timeout"]["read"] <= 75


def test_quota_error_is_preserved(capsys, monkeypatch, tmp_path):
    with respx.mock as transport:
        route = transport.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/context/search").respond(
            402,
            json={
                "request_id": "quota-test",
                "error": {
                    "code": "EMBEDDING_QUOTA_EXHAUSTED",
                    "message": "Query allowance exhausted.",
                },
            },
        )
        rc, out, err = run_cli(
            context_args("search", "docs", "--text", "hello"), capsys, monkeypatch, tmp_path
        )
    assert rc != 0
    assert "EMBEDDING_QUOTA_EXHAUSTED" in out + err
    assert len(route.calls) == 1
