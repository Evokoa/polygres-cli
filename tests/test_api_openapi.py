from __future__ import annotations

import json

import pytest

from polygres_cli.api_openapi import (
    SNAPSHOT_VERSION,
    api_route_rows,
    build_api_request_plan,
    inspect_api_operation,
    list_api_operations,
    load_openapi_snapshot,
    resolve_api_operation,
)
from polygres_cli.cli_errors import UsageError

PROJECT_ID = "p0123456789abcdef0123456"


def test_bundled_snapshot_has_versioned_control_plane_metadata() -> None:
    document = load_openapi_snapshot()

    assert document["x-polygres-cli-snapshot-version"] == SNAPSHOT_VERSION
    assert document["openapi"].startswith("3.")
    assert "/v1/projects" in document["paths"]
    assert "/v1/cli/notices" in document["paths"]
    assert "CliNoticeResponse" in document["components"]["schemas"]
    assert len(list_api_operations()) > 100


def test_route_rows_use_cli_relative_paths_and_method_filter() -> None:
    rows = api_route_rows(method="get")

    assert rows
    assert {row["method"] for row in rows} == {"GET"}
    assert all(row["route"].startswith("/") for row in rows)
    assert all(not row["route"].startswith("/v1/") for row in rows)
    assert any(row["route"] == "/projects" for row in rows)


def test_resolve_route_requires_method_when_path_has_multiple_operations() -> None:
    with pytest.raises(UsageError) as exc_info:
        resolve_api_operation("/projects")

    assert exc_info.value.code == "API_METHOD_REQUIRED"

    operation = resolve_api_operation("/v1/projects", method="post")
    assert operation.method == "POST"
    assert operation.operation_id == "create_project_v1_projects_post"


def test_resolve_route_accepts_exact_operation_id() -> None:
    operation = resolve_api_operation("get_project_v1_projects__project_id__get")

    assert operation.route == "/projects/{project_id}"
    assert operation.method == "GET"


@pytest.mark.parametrize(
    "route",
    [
        "https://example.test/v1/projects",
        "//example.test/projects",
        "/projects?limit=1",
        "/projects#fragment",
    ],
)
def test_resolve_route_rejects_urls_and_non_bundled_routes(route: str) -> None:
    with pytest.raises(UsageError) as exc_info:
        resolve_api_operation(route, method="GET")

    assert exc_info.value.code == "API_ROUTE_NOT_FOUND"


def test_request_plan_substitutes_declared_path_and_query_parameters() -> None:
    operation = resolve_api_operation(
        "/projects/{project_id}/tables/{schema_name}/{table_name}/rows",
        method="GET",
    )
    plan = build_api_request_plan(
        operation,
        [
            "schema_name=public",
            "table_name=documents",
            "limit=25",
            "cursor=next-page",
        ],
        default_project_id=PROJECT_ID,
    )

    assert plan.path == f"/projects/{PROJECT_ID}/tables/public/documents/rows"
    assert ("limit", "25") in plan.query
    assert ("cursor", "next-page") in plan.query
    assert plan.request_path.endswith("?limit=25&cursor=next-page")


def test_request_plan_rejects_unknown_parameters_and_path_separators() -> None:
    operation = resolve_api_operation("/projects/{project_id}", method="GET")

    with pytest.raises(UsageError) as unknown:
        build_api_request_plan(operation, ["not_declared=value"], default_project_id=PROJECT_ID)
    assert unknown.value.code == "API_PARAMETER_NOT_FOUND"

    with pytest.raises(UsageError) as separator:
        build_api_request_plan(operation, ["project_id=../admin"])
    assert separator.value.code == "API_PARAMETER_INVALID"


def test_request_plan_validates_json_body_against_openapi_schema() -> None:
    operation = resolve_api_operation("/projects", method="POST")

    plan = build_api_request_plan(
        operation,
        [],
        body={"name": "Support"},
        body_provided=True,
    )
    assert plan.body == {"name": "Support"}
    assert plan.has_body is True

    with pytest.raises(UsageError) as missing:
        build_api_request_plan(operation, [], body={}, body_provided=True)
    assert missing.value.code == "API_BODY_INVALID"

    with pytest.raises(UsageError) as absent:
        build_api_request_plan(operation, [])
    assert absent.value.code == "API_BODY_REQUIRED"


def test_request_plan_rejects_body_for_route_without_request_body() -> None:
    operation = resolve_api_operation("/projects", method="GET")

    with pytest.raises(UsageError) as exc_info:
        build_api_request_plan(operation, [], body={}, body_provided=True)

    assert exc_info.value.code == "API_BODY_NOT_ALLOWED"


def test_schema_inspection_includes_transitive_component_schemas() -> None:
    operation = resolve_api_operation("/projects", method="POST")
    schema = inspect_api_operation(operation)

    assert schema["route"] == "/projects"
    assert schema["method"] == "POST"
    assert schema["request_body"]["content"]["application/json"]["schema"]["$ref"].startswith(
        "#/components/schemas/"
    )
    assert schema["components"]["schemas"]
    assert json.dumps(schema)
