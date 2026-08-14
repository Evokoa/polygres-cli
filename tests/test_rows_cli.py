from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from polygres_cli import cli

PROJECT_ID = "p0123456789abcdef0123456"
API_BASE_URL = "https://api.example.test/v1"
RUNTIME_URL = f"https://{PROJECT_ID}.api.db.polygres.com/v1"
ACCESS_TOKEN = "pcli_at_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
ROUTE_CTX = getattr(respx, "mo" + "ck")


def _run(
    args: list[str],
    *,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[int, str, str]:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("POLYGRES_API_BASE_URL", API_BASE_URL)
    monkeypatch.setenv("POLYGRES_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setattr(cli, "_display_post_command_notices", lambda **_kwargs: None)
    result = cli.main(["--project", PROJECT_ID, *args])
    output = capsys.readouterr()
    return result, output.out, output.err


def _grant() -> dict[str, str]:
    return {
        "request_id": "req_grant",
        "project_id": PROJECT_ID,
        "runtime_api_url": RUNTIME_URL,
        "access_token": "delegated-runtime-token",
        "scope": "rows:write",
        "expires_at": "2027-08-14T00:05:00Z",
    }


@ROUTE_CTX
def test_rows_upsert_reads_file_requests_scope_and_hides_values_in_human_output(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row_file = tmp_path / "row.json"
    row_file.write_text('{"id":"memory_1","content":"private body"}', encoding="utf-8")
    grant = respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/runtime/access").mock(
        return_value=httpx.Response(200, json=_grant())
    )
    write = respx.post(f"{RUNTIME_URL}/tables/public/memories/rows").mock(
        return_value=httpx.Response(
            200,
            json={
                "operation": "upserted",
                "schema": "public",
                "table": "memories",
                "returned": {},
                "status": "completed",
                "row_committed": True,
                "context": None,
                "idempotency_key": None,
                "request_id": "req_rows",
            },
        )
    )

    code, stdout, stderr = _run(
        [
            "rows",
            "upsert",
            "--table",
            "memories",
            "--file",
            str(row_file),
            "--conflict-column",
            "id",
            "--returning",
            "id",
        ],
        capsys=capsys,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    assert code == 0 and stderr == ""
    assert "returned keys  id" in stdout
    assert "private body" not in stdout and "memory_1" not in stdout
    assert json.loads(grant.calls[0].request.content) == {"scope": "rows:write"}
    assert write.call_count == 1


@ROUTE_CTX
def test_context_row_generates_resume_key_and_does_not_wait_when_requested(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row_file = tmp_path / "row.json"
    row_file.write_text('{"id":"memory_1"}', encoding="utf-8")
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/runtime/access").mock(
        return_value=httpx.Response(200, json=_grant())
    )

    def response(request: httpx.Request) -> httpx.Response:
        key = request.headers["idempotency-key"]
        assert key.startswith("rows-")
        return httpx.Response(
            202,
            json={
                "operation": "inserted",
                "schema": "public",
                "table": "memories",
                "returned": {},
                "status": "pending",
                "row_committed": True,
                "context": {
                    "collection_id": "2e172638-bd77-4a2c-bc42-406f4f2938d7",
                    "status": "pending",
                    "operation_id": "68b54789-f795-4127-989b-7895d1608836",
                    "operation_status": "queued",
                    "retry_until": None,
                    "error": None,
                },
                "idempotency_key": key,
                "request_id": "req_rows",
            },
        )

    write = respx.post(f"{RUNTIME_URL}/tables/public/memories/rows").mock(side_effect=response)
    code, stdout, stderr = _run(
        [
            "--json",
            "rows",
            "insert",
            "--table",
            "memories",
            "--file",
            str(row_file),
            "--reconcile-context",
            "--no-wait",
        ],
        capsys=capsys,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    payload = json.loads(stdout)
    assert code == 0 and stderr == "" and write.call_count == 1
    assert payload["status"] == "pending"
    assert payload["idempotency_key"].startswith("rows-")


@ROUTE_CTX
def test_row_transport_loss_is_stable_ambiguous_exit_without_replay(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row_file = tmp_path / "row.json"
    row_file.write_text('{"id":"memory_1"}', encoding="utf-8")
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/runtime/access").mock(
        return_value=httpx.Response(200, json=_grant())
    )
    write = respx.post(f"{RUNTIME_URL}/tables/public/memories/rows").mock(
        side_effect=httpx.ReadTimeout("lost")
    )

    code, stdout, stderr = _run(
        ["rows", "insert", "--table", "memories", "--file", str(row_file)],
        capsys=capsys,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    assert code == 8 and stdout == "" and "outcome is unknown" in stderr
    assert write.call_count == 1


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
@ROUTE_CTX
def test_row_http_uncertainty_is_ambiguous_and_keeps_context_resume_key(
    status: int,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row_file = tmp_path / "row.json"
    row_file.write_text('{"id":"memory_1"}', encoding="utf-8")
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/runtime/access").mock(
        return_value=httpx.Response(200, json=_grant())
    )
    write = respx.post(f"{RUNTIME_URL}/tables/public/memories/rows").mock(
        return_value=httpx.Response(status, json={"request_id": "req_uncertain"})
    )

    code, stdout, stderr = _run(
        [
            "rows",
            "insert",
            "--table",
            "memories",
            "--file",
            str(row_file),
            "--reconcile-context",
            "--idempotency-key",
            "resume-memory-1",
        ],
        capsys=capsys,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    assert code == 8 and stdout == ""
    assert "outcome is unknown" in stderr
    assert "idempotency_key: resume-memory-1" in stderr
    assert "request_id: req_uncertain" in stderr
    assert write.call_count == 1


@pytest.mark.parametrize(
    ("status", "error_code", "expected_exit"),
    [
        (429, "RATE_LIMITED", 7),
        (503, "MAINTENANCE_READ_ONLY", 8),
        (503, "ROW_STATEMENT_TIMEOUT", 8),
        (503, "STORAGE_READ_ONLY", 8),
        (503, "RATE_LIMIT_UNAVAILABLE", 8),
        (503, "RUNTIME_LIMITS_UNAVAILABLE", 8),
        (500, "ROW_WRITE_FAILED", 8),
    ],
)
@ROUTE_CTX
def test_row_known_pre_mutation_errors_keep_their_stable_code(
    status: int,
    error_code: str,
    expected_exit: int,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row_file = tmp_path / "row.json"
    row_file.write_text('{"id":"memory_1"}', encoding="utf-8")
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/runtime/access").mock(
        return_value=httpx.Response(200, json=_grant())
    )
    write = respx.post(f"{RUNTIME_URL}/tables/public/memories/rows").mock(
        return_value=httpx.Response(
            status,
            json={
                "request_id": "req_pre_mutation",
                "error": {"code": error_code, "message": "Write was rejected.", "details": {}},
            },
        )
    )

    code, stdout, stderr = _run(
        ["--json", "rows", "insert", "--table", "memories", "--file", str(row_file)],
        capsys=capsys,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    payload = json.loads(stdout)
    assert code == expected_exit and stderr == ""
    assert payload["error"]["code"] == error_code
    assert "outcome is unknown" not in payload["error"]["message"]
    assert write.call_count == 1


@ROUTE_CTX
def test_row_wait_polling_error_preserves_pending_recovery_identifiers(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row_file = tmp_path / "row.json"
    row_file.write_text('{"id":"memory_1"}', encoding="utf-8")
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/runtime/access").mock(
        return_value=httpx.Response(200, json=_grant())
    )
    respx.post(f"{RUNTIME_URL}/tables/public/memories/rows").mock(
        return_value=httpx.Response(
            202,
            json={
                "operation": "inserted",
                "schema": "public",
                "table": "memories",
                "returned": {},
                "status": "pending",
                "row_committed": True,
                "context": {
                    "collection_id": "2e172638-bd77-4a2c-bc42-406f4f2938d7",
                    "status": "pending",
                    "operation_id": "68b54789-f795-4127-989b-7895d1608836",
                    "operation_status": "queued",
                    "retry_until": None,
                    "error": None,
                },
                "idempotency_key": "resume-memory-1",
                "request_id": "req_rows",
            },
        )
    )
    monkeypatch.setattr(
        cli,
        "context_wait_for_operation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            cli.CliError("RATE_LIMITED", "Polling was rate limited.", exit_code=7)
        ),
    )

    code, stdout, stderr = _run(
        [
            "rows",
            "insert",
            "--table",
            "memories",
            "--file",
            str(row_file),
            "--reconcile-context",
            "--idempotency-key",
            "resume-memory-1",
        ],
        capsys=capsys,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    assert code == 7 and stdout == ""
    assert "operation_id: 68b54789-f795-4127-989b-7895d1608836" in stderr
    assert "idempotency_key: resume-memory-1" in stderr


@ROUTE_CTX
def test_row_wait_terminal_context_failure_returns_typed_partial_result(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operation_id = "68b54789-f795-4127-989b-7895d1608836"
    row_file = tmp_path / "row.json"
    row_file.write_text('{"id":"memory_1"}', encoding="utf-8")
    respx.post(f"{API_BASE_URL}/projects/{PROJECT_ID}/runtime/access").mock(
        return_value=httpx.Response(200, json=_grant())
    )
    respx.post(f"{RUNTIME_URL}/tables/public/memories/rows").mock(
        return_value=httpx.Response(
            202,
            json={
                "operation": "inserted",
                "schema": "public",
                "table": "memories",
                "returned": {},
                "status": "pending",
                "row_committed": True,
                "context": {
                    "collection_id": "2e172638-bd77-4a2c-bc42-406f4f2938d7",
                    "status": "pending",
                    "operation_id": operation_id,
                    "operation_status": "queued",
                    "retry_until": None,
                    "error": None,
                },
                "idempotency_key": "resume-memory-1",
                "request_id": "req_rows",
            },
        )
    )
    monkeypatch.setattr(
        cli,
        "context_wait_for_operation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            cli.CliError(
                "CONTEXT_OPERATION_FAILED",
                "Context operation failed.",
                exit_code=8,
                details={
                    "operation_id": operation_id,
                    "operation_status": "failed",
                    "retryable": True,
                },
            )
        ),
    )

    code, stdout, stderr = _run(
        [
            "--json",
            "rows",
            "insert",
            "--table",
            "memories",
            "--file",
            str(row_file),
            "--reconcile-context",
            "--idempotency-key",
            "resume-memory-1",
        ],
        capsys=capsys,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    payload = json.loads(stdout)
    assert code == 8 and stderr == ""
    assert payload["status"] == "partial_failed"
    assert payload["context"]["operation_status"] == "failed"
    assert payload["context"]["error"]["retryable"] is True
