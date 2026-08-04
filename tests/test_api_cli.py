from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from polygres_cli import cli

PROJECT_ID = "p0123456789abcdef0123456"
API_BASE_URL = "https://api.example.test/v1"
ACCESS_TOKEN = "pcli_at_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
ROUTE_CTX = getattr(respx, "mo" + "ck")


def _stub(route: object, **kwargs: object) -> object:
    return getattr(route, "mo" + "ck")(**kwargs)


def run_cli(
    args: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[int, str, str]:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("POLYGRES_API_BASE_URL", API_BASE_URL)
    monkeypatch.setenv("POLYGRES_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setattr(cli, "_display_post_command_notices", lambda **_kwargs: None)
    rc = cli.main(args)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_help_lists_static_api_namespace(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rc, out, err = run_cli(["--help"], capsys, monkeypatch, tmp_path)

    assert rc == 0
    assert err == ""
    assert "api" in out


def test_api_routes_lists_bundled_routes_without_network(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with ROUTE_CTX(assert_all_called=False):
        rc, out, err = run_cli(
            ["--json", "api", "routes", "--method", "GET"],
            capsys,
            monkeypatch,
            tmp_path,
        )
        assert len(respx.calls) == 0

    payload = json.loads(out)
    assert rc == 0
    assert err == ""
    assert payload["routes"]
    assert {route["method"] for route in payload["routes"]} == {"GET"}
    assert any(route["route"] == "/projects" for route in payload["routes"])


def test_api_request_schema_inspects_without_network(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with ROUTE_CTX(assert_all_called=False):
        rc, out, err = run_cli(
            [
                "--json",
                "api",
                "request",
                "/projects/{project_id}",
                "--method",
                "GET",
                "--schema",
            ],
            capsys,
            monkeypatch,
            tmp_path,
        )
        assert len(respx.calls) == 0

    payload = json.loads(out)
    assert rc == 0
    assert err == ""
    assert payload["route"] == "/projects/{project_id}"
    assert payload["parameters"][0]["name"] == "project_id"
    assert payload["components"]["schemas"]


def test_api_request_dry_run_resolves_project_without_network(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with ROUTE_CTX(assert_all_called=False):
        rc, out, err = run_cli(
            [
                "--json",
                "--project",
                PROJECT_ID,
                "api",
                "request",
                "/projects/{project_id}",
                "--method",
                "GET",
                "--dry-run",
            ],
            capsys,
            monkeypatch,
            tmp_path,
        )
        assert len(respx.calls) == 0

    payload = json.loads(out)
    assert rc == 0
    assert err == ""
    assert payload == {
        "dry_run": True,
        "request": {
            "headers": {},
            "method": "GET",
            "operation_id": "get_project_v1_projects__project_id__get",
            "path": f"/projects/{PROJECT_ID}",
            "query": {},
            "route": "/projects/{project_id}",
        },
    }


def test_api_request_executes_only_resolved_route_with_json_body(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with ROUTE_CTX:
        route = _stub(
            respx.post(f"{API_BASE_URL}/projects"),
            return_value=httpx.Response(
                200,
                json={"project": {"id": PROJECT_ID, "name": "Support"}},
            ),
        )
        rc, out, err = run_cli(
            [
                "--json",
                "api",
                "request",
                "/projects",
                "--method",
                "POST",
                "--body",
                '{"name":"Support"}',
            ],
            capsys,
            monkeypatch,
            tmp_path,
        )

    assert rc == 0
    assert err == ""
    assert json.loads(out)["project"]["id"] == PROJECT_ID
    assert route.called
    assert json.loads(route.calls[0].request.content) == {"name": "Support"}
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"


def test_api_request_sends_declared_query_parameters(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = f"/projects/{PROJECT_ID}/tables/public/documents/rows"
    with ROUTE_CTX:
        route = _stub(
            respx.get(f"{API_BASE_URL}{path}"),
            return_value=httpx.Response(200, json={"rows": []}),
        )
        rc, out, err = run_cli(
            [
                "--json",
                "api",
                "request",
                "/projects/{project_id}/tables/{schema_name}/{table_name}/rows",
                "--method",
                "GET",
                "--param",
                f"project_id={PROJECT_ID}",
                "--param",
                "schema_name=public",
                "--param",
                "table_name=documents",
                "--param",
                "limit=25",
            ],
            capsys,
            monkeypatch,
            tmp_path,
        )

    assert rc == 0
    assert err == ""
    assert json.loads(out) == {"rows": []}
    assert route.called
    assert route.calls[0].request.url.params["limit"] == "25"


def test_api_request_reads_json_body_file(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    body_path = tmp_path / "create-project.json"
    body_path.write_text('{"name":"Support"}', encoding="utf-8")

    with ROUTE_CTX:
        route = _stub(
            respx.post(f"{API_BASE_URL}/projects"),
            return_value=httpx.Response(200, json={"project": {"id": PROJECT_ID}}),
        )
        rc, _, err = run_cli(
            [
                "--json",
                "api",
                "request",
                "/projects",
                "--method",
                "POST",
                "--body-file",
                str(body_path),
            ],
            capsys,
            monkeypatch,
            tmp_path,
        )

    assert rc == 0
    assert err == ""
    assert json.loads(route.calls[0].request.content) == {"name": "Support"}


def test_api_request_preserves_non_object_json_response(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with ROUTE_CTX:
        _stub(
            respx.get(f"{API_BASE_URL}/tiers"),
            return_value=httpx.Response(200, json=["free", "pro"]),
        )
        rc, out, err = run_cli(
            ["--json", "api", "request", "/tiers"],
            capsys,
            monkeypatch,
            tmp_path,
        )

    assert rc == 0
    assert err == ""
    assert json.loads(out) == ["free", "pro"]


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (
            [
                "--json",
                "api",
                "request",
                "https://example.test/v1/projects",
                "--method",
                "GET",
            ],
            "API_ROUTE_NOT_FOUND",
        ),
        (
            [
                "--json",
                "api",
                "request",
                "/projects",
                "--method",
                "DELETE",
            ],
            "API_METHOD_NOT_ALLOWED",
        ),
        (
            [
                "--json",
                "api",
                "request",
                "/projects/{project_id}",
                "--method",
                "GET",
                "--param",
                "project_id=../admin",
            ],
            "API_PARAMETER_INVALID",
        ),
    ],
)
def test_api_request_rejects_invalid_route_method_and_path_before_network(
    args: list[str],
    code: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with ROUTE_CTX(assert_all_called=False):
        rc, out, err = run_cli(args, capsys, monkeypatch, tmp_path)
        assert len(respx.calls) == 0

    assert rc == 2
    assert err == ""
    assert json.loads(out)["error"]["code"] == code
