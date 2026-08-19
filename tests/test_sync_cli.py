from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from polygres_cli import cli
from polygres_cli.sync_inputs import sync_stage_idempotency_key

API_BASE_URL = "https://api.example.test/v1"
ACCESS_TOKEN = "pcli_at_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
ATTEMPT_ID = "pf0123456789abcdefghijkl"
PROJECT_ID = "p0123456789abcdef0123456"
ROUTE_CTX = getattr(respx, "mo" + "ck")


def _stub(route: object, **kwargs: object) -> object:
    return getattr(route, "mo" + "ck")(**kwargs)


def _run_cli(
    args: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[int, str, str]:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("POLYGRES_CONFIG_PATH", raising=False)
    monkeypatch.setenv("POLYGRES_API_BASE_URL", API_BASE_URL)
    monkeypatch.setenv("POLYGRES_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setattr(cli, "_display_post_command_notices", lambda **_kwargs: None)
    rc = cli.main(args)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _preflight(
    *,
    status: str = "source_ready",
    selection_generation: int = 0,
    selected_count: int = 0,
) -> dict[str, object]:
    return {
        "attempt_id": ATTEMPT_ID,
        "status": status,
        "attempt_generation": 1,
        "selection_generation": selection_generation,
        "selection": {"selected_count": selected_count},
        "valid_actions": ["list_tables", "update_selection", "create_project"],
    }


def _preflight_response(**kwargs: object) -> dict[str, object]:
    return {"request_id": "req_sync", "preflight": _preflight(**kwargs)}


def _options_response(*, enabled: bool = True) -> dict[str, object]:
    return {
        "request_id": "req_options",
        "options": {
            "synced_projects_enabled": enabled,
            "disabled_reason": None if enabled else "Not available for this organization.",
            "region": "eastus",
            "egress_ips": [{"region": "eastus", "ip": "203.0.113.10"}],
        },
    }


def _table(
    name: str = "orders",
    *,
    eligible: bool = True,
) -> dict[str, object]:
    return {
        "schema_name": "public",
        "table_name": name,
        "eligible": eligible,
        "estimated_rows": 12,
        "estimated_total_bytes": 4096,
        "sync_key": None,
        "sync_key_candidates": [
            {
                "kind": "unique_index",
                "index_name": f"{name}_external_id_key",
                "columns": ["external_id"],
            }
        ],
    }


def test_sync_help_is_one_project_creation_command(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rc, out, err = _run_cli(
        ["projects", "create", "sync", "--help"], capsys, monkeypatch, tmp_path
    )

    assert rc == 0
    assert err == ""
    assert "Polygres project name" in out
    assert "--connection-env" in out
    assert "--table" in out
    assert "--all-eligible" in out
    assert "preflight" not in out.lower()
    assert "attempt" not in out.lower()


def test_sync_create_requires_confirmation_before_connecting(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rc, out, err = _run_cli(
        [
            "--json",
            "projects",
            "create",
            "sync",
            "Analytics",
            "--connection-env",
            "SOURCE_DATABASE_URL",
            "--all-eligible",
        ],
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 2
    assert err == ""
    assert json.loads(out)["error"]["code"] == "CONFIRMATION_REQUIRED"


def test_sync_create_requires_secret_safe_connection_input_noninteractively(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rc, out, err = _run_cli(
        [
            "--json",
            "projects",
            "create",
            "sync",
            "Analytics",
            "--all-eligible",
            "--yes",
        ],
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 2
    assert err == ""
    payload = json.loads(out)
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert "--connection-env" in payload["error"]["message"]


@ROUTE_CTX
def test_sync_create_orchestrates_inspection_selection_and_project_creation(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_url = "postgresql://sync_user:super-secret@db.example.test/app"
    monkeypatch.setenv("SOURCE_DATABASE_URL", secret_url)
    _stub(
        respx.get(f"{API_BASE_URL}/project-creation-options"),
        return_value=httpx.Response(200, json=_options_response()),
    )
    preflight_route = _stub(
        respx.post(f"{API_BASE_URL}/project-preflights"),
        return_value=httpx.Response(200, json=_preflight_response()),
    )
    _stub(
        respx.get(f"{API_BASE_URL}/project-preflights/{ATTEMPT_ID}/tables?limit=200"),
        return_value=httpx.Response(
            200,
            json={"request_id": "req_tables", "tables": [_table()], "next_cursor": None},
        ),
    )
    selection_route = _stub(
        respx.put(f"{API_BASE_URL}/project-preflights/{ATTEMPT_ID}/selection"),
        return_value=httpx.Response(
            200,
            json=_preflight_response(selection_generation=1, selected_count=1),
        ),
    )
    create_route = _stub(
        respx.post(f"{API_BASE_URL}/projects"),
        return_value=httpx.Response(
            200,
            json={
                "request_id": "req_create",
                "project": {
                    "external_id": PROJECT_ID,
                    "name": "Analytics",
                    "status": "provisioning",
                    "project_mode": "synced",
                },
            },
        ),
    )

    rc, out, err = _run_cli(
        [
            "--json",
            "projects",
            "create",
            "sync",
            "Analytics",
            "--connection-env",
            "SOURCE_DATABASE_URL",
            "--table",
            "public.orders",
            "--yes",
            "--no-wait",
            "--idempotency-key",
            "sync-workflow-1",
        ],
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    assert secret_url not in out
    assert secret_url not in err
    assert json.loads(preflight_route.calls.last.request.content) == {
        "project_type": "postgres_sync",
        "connection": {"url": secret_url},
    }
    assert preflight_route.calls.last.request.headers["Idempotency-Key"] == (
        sync_stage_idempotency_key("sync-workflow-1", "source")
    )
    assert json.loads(selection_route.calls.last.request.content) == {
        "expected_selection_generation": 0,
        "tables": [
            {
                "schema_name": "public",
                "table_name": "orders",
                "sync_key_index_name": "orders_external_id_key",
            }
        ],
    }
    create_body = json.loads(create_route.calls.last.request.content)
    assert create_body["project_type"] == "postgres_sync"
    assert create_body["preflight_attempt_id"] == ATTEMPT_ID
    assert create_body["expected_selection_generation"] == 1
    assert create_body["confirmations"] == {
        "source_authority": True,
        "mutation_restrictions": True,
        "fixed_table_selection": True,
        "managed_replication_resources": True,
        "no_database_credentials": True,
    }
    output = json.loads(out)
    assert output["project"]["external_id"] == PROJECT_ID
    assert output["selected_table_count"] == 1
    assert output["idempotency_key"] == "sync-workflow-1"
    assert "preflight" not in output


@ROUTE_CTX
def test_sync_create_all_eligible_selects_discovered_tables(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SOURCE_DATABASE_URL", "postgresql://user:secret@host/db")
    _stub(
        respx.get(f"{API_BASE_URL}/project-creation-options"),
        return_value=httpx.Response(200, json=_options_response()),
    )
    _stub(
        respx.post(f"{API_BASE_URL}/project-preflights"),
        return_value=httpx.Response(200, json=_preflight_response()),
    )
    _stub(
        respx.get(f"{API_BASE_URL}/project-preflights/{ATTEMPT_ID}/tables?limit=200"),
        return_value=httpx.Response(
            200,
            json={
                "request_id": "req_tables",
                "tables": [_table("orders"), _table("audit", eligible=False)],
                "next_cursor": None,
            },
        ),
    )
    selection_route = _stub(
        respx.put(f"{API_BASE_URL}/project-preflights/{ATTEMPT_ID}/selection"),
        return_value=httpx.Response(
            200,
            json=_preflight_response(selection_generation=1, selected_count=1),
        ),
    )
    _stub(
        respx.post(f"{API_BASE_URL}/projects"),
        return_value=httpx.Response(
            200,
            json={
                "request_id": "req_create",
                "project": {
                    "external_id": PROJECT_ID,
                    "name": "Analytics",
                    "status": "provisioning",
                    "project_mode": "synced",
                },
            },
        ),
    )

    rc, _, _ = _run_cli(
        [
            "--json",
            "projects",
            "create",
            "sync",
            "Analytics",
            "--connection-env",
            "SOURCE_DATABASE_URL",
            "--all-eligible",
            "--yes",
            "--no-wait",
        ],
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 0
    tables = json.loads(selection_route.calls.last.request.content)["tables"]
    assert [table["table_name"] for table in tables] == ["orders"]


@ROUTE_CTX
def test_sync_create_reports_source_failure_with_allowlist_ips(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SOURCE_DATABASE_URL", "postgresql://user:secret@host/db")
    _stub(
        respx.get(f"{API_BASE_URL}/project-creation-options"),
        return_value=httpx.Response(200, json=_options_response()),
    )
    failure = _preflight_response(status="connection_failed")
    failure["preflight"]["checks"] = [  # type: ignore[index]
        {"code": "SOURCE_CONNECTIVITY", "status": "failed"}
    ]
    failure["preflight"]["failure"] = {  # type: ignore[index]
        "code": "SOURCE_UNREACHABLE",
        "message": "The source could not be reached.",
    }
    _stub(
        respx.post(f"{API_BASE_URL}/project-preflights"),
        return_value=httpx.Response(200, json=failure),
    )

    rc, out, err = _run_cli(
        [
            "--json",
            "projects",
            "create",
            "sync",
            "Analytics",
            "--connection-env",
            "SOURCE_DATABASE_URL",
            "--all-eligible",
            "--yes",
        ],
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 1
    assert err == ""
    payload = json.loads(out)
    assert payload["error"]["code"] == "SOURCE_UNREACHABLE"
    assert payload["error"]["details"]["source_allowlist_ips"] == ["203.0.113.10"]
    assert "preflight" not in payload["error"]["message"].lower()


@ROUTE_CTX
def test_sync_create_requires_table_choice_for_noninteractive_use(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SOURCE_DATABASE_URL", "postgresql://user:secret@host/db")
    _stub(
        respx.get(f"{API_BASE_URL}/project-creation-options"),
        return_value=httpx.Response(200, json=_options_response()),
    )
    _stub(
        respx.post(f"{API_BASE_URL}/project-preflights"),
        return_value=httpx.Response(200, json=_preflight_response()),
    )
    _stub(
        respx.get(f"{API_BASE_URL}/project-preflights/{ATTEMPT_ID}/tables?limit=200"),
        return_value=httpx.Response(
            200,
            json={"request_id": "req_tables", "tables": [_table()], "next_cursor": None},
        ),
    )

    rc, out, _ = _run_cli(
        [
            "--json",
            "projects",
            "create",
            "sync",
            "Analytics",
            "--connection-env",
            "SOURCE_DATABASE_URL",
            "--yes",
        ],
        capsys,
        monkeypatch,
        tmp_path,
    )

    assert rc == 2
    assert json.loads(out)["error"]["code"] == "SYNC_TABLE_SELECTION_REQUIRED"
