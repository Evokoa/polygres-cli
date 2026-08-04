from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from polygres_cli.context_output import (
    context_capabilities_human,
    context_collection_get_human,
    context_collection_status_human,
    context_collections_list_human,
    context_count_human,
    context_diagnostics_human,
    context_discovery_human,
    context_facets_human,
    context_filters_human,
    context_joint_human,
    context_operation_human,
    context_operations_list_human,
    context_point_status_human,
    context_points_scroll_human,
    context_preflight_human,
    context_recall_human,
    context_verification_human,
)

HumanRenderer = Callable[[dict[str, Any]], None]


def _render(function: Callable[..., None], **kwargs: Any) -> HumanRenderer:
    return lambda payload: function(payload, verbose=False, **kwargs)


@pytest.mark.parametrize(
    ("renderer", "payload", "expected"),
    [
        (
            _render(context_capabilities_human),
            {
                "joint": True,
                "joint_blocker": None,
                "max_joint_seed_limit": 32,
                "max_joint_traversal_limit": 1000,
            },
            ["Joint", "Available", "Joint seed limit", "32", "1000"],
        ),
        (
            _render(context_discovery_human),
            {
                "candidates": [
                    {
                        "classification": "ready_to_configure",
                        "source": {
                            "schema_name": "public",
                            "table_name": "docs",
                            "source_key_column": "id",
                            "source_key_type": "uuid",
                        },
                        "vectors": [
                            {
                                "column_name": "embedding",
                                "type_owner": "pgcontext",
                                "dimensions": 3,
                            }
                        ],
                        "reasons": [],
                    }
                ]
            },
            ["CLASS", "ready_to_configure", "public.docs", "pgcontext"],
        ),
        (
            _render(context_preflight_human, quiet=False),
            {
                "eligible": False,
                "classification": "needs_setup",
                "source_identity": {"schema_name": "public", "table_name": "docs"},
                "checks": [
                    {
                        "code": "source_key",
                        "status": "blocked",
                        "message": "Source key is not ready.",
                    }
                ],
                "planned_actions": [],
            },
            ["Eligible", "No", "Classification", "CHECK", "blocked"],
        ),
        (
            _render(context_collections_list_human),
            {
                "collections": [
                    {
                        "id": "collection-id",
                        "name": "docs",
                        "schema_name": "public",
                        "table_name": "docs",
                        "vector_column": "embedding",
                        "dimensions": 3,
                        "metric": "cosine",
                        "index_status": "ready",
                        "mapped_point_count": 2,
                        "is_default": True,
                        "status": "ready",
                    }
                ]
            },
            ["ID", "NAME", "SOURCE", "public.docs", "POINTS", "DEFAULT"],
        ),
        (
            _render(context_collection_get_human),
            {
                "collection": {
                    "id": "collection-id",
                    "name": "docs",
                    "status": "ready",
                    "is_default": True,
                    "schema_name": "public",
                    "table_name": "docs",
                    "source_key_column": "id",
                    "vector_column": "embedding",
                    "dimensions": 3,
                    "metric": "cosine",
                    "result_columns": ["title"],
                    "filter_columns": ["tenant_id"],
                }
            },
            ["Name", "docs", "Source key", "Result columns", "tenant_id"],
        ),
        (
            _render(context_collection_status_human),
            {
                "collection_name": "docs",
                "status": "ready",
                "serving_status": "available",
                "index_status": "ready",
                "point_reconciliation_status": "current",
                "mapped_point_count": 2,
                "active_operation": None,
            },
            ["Collection", "Serving", "available", "Points", "current"],
        ),
        (
            _render(context_verification_human),
            {
                "collection_name": "docs",
                "verified": False,
                "checked_at": "2026-07-29T00:00:00Z",
                "checks": [
                    {
                        "name": "point_mappings",
                        "status": "fail",
                        "code": "CONTEXT_POINT_RECONCILIATION_STALE",
                        "message": "Mappings are stale.",
                    }
                ],
            },
            ["Verified", "no", "point_mappings", "CONTEXT_POINT_RECONCILIATION_STALE"],
        ),
        (
            _render(context_diagnostics_human),
            {
                "collection_name": "docs",
                "overall_status": "degraded",
                "checked_at": "2026-07-29T00:00:00Z",
                "checks": [
                    {
                        "name": "index",
                        "status": "warning",
                        "code": "CONTEXT_INDEX_STALE",
                        "message": "Index is stale.",
                    }
                ],
            },
            ["Overall", "degraded", "index", "warning"],
        ),
        (
            _render(context_filters_human),
            {
                "filters": [
                    {
                        "key": "topic",
                        "kind": "jsonb_path",
                        "column": "metadata",
                        "path": ["topic"],
                    }
                ]
            },
            ["KEY", "KIND", "SOURCE", "metadata.topic"],
        ),
        (
            _render(context_point_status_human),
            {
                "collection_id": "collection-id",
                "status": "current",
                "mapped_point_count": 2,
                "last_error_code": None,
                "last_error_stage": None,
                "active_operation": None,
            },
            ["Status", "current", "Mapped", "Error code"],
        ),
        (
            _render(context_points_scroll_human),
            {"points": [{"point_id": 1, "source_key": "doc_1"}]},
            ["POINT ID", "SOURCE KEY", "doc_1"],
        ),
        (
            _render(context_operations_list_human),
            {
                "operations": [
                    {
                        "id": "operation-id",
                        "kind": "points_reconcile",
                        "collection_id": "collection-id",
                        "status": "running",
                        "stage": "scanning_source",
                        "processed_units": 2,
                        "total_units": 10,
                        "attempts": 1,
                    }
                ]
            },
            ["KIND", "points_reconcile", "PROCESSED", "ATTEMPTS"],
        ),
        (
            _render(context_operation_human),
            {
                "operation": {
                    "id": "operation-id",
                    "kind": "points_reconcile",
                    "status": "failed",
                    "stage": "failed",
                    "error": {
                        "code": "CONTEXT_OPERATION_FAILED",
                        "message": "Operation failed.",
                        "retryable": True,
                    },
                    "result": {"retry_of": "old-operation-id"},
                }
            },
            ["Operation", "Error code", "Retryable", "Retry of"],
        ),
        (
            _render(context_count_human),
            {"count": 42},
            ["Count", "42"],
        ),
        (
            _render(context_facets_human),
            {"facets": [{"value": "open", "count": 3}]},
            ["VALUE", "COUNT", "open"],
        ),
        (
            _render(context_recall_human),
            {
                "exact_count": 10,
                "candidate_count": 10,
                "intersection_count": 9,
                "recall": 0.9,
                "minimum_recall": 0.95,
                "status": "failing",
            },
            ["Recall", "0.900000", "Minimum", "0.950000", "failing"],
        ),
    ],
)
def test_context_human_output_views(
    renderer: HumanRenderer,
    payload: dict[str, Any],
    expected: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    renderer(payload)

    output = capsys.readouterr().out
    for value in expected:
        assert value in output


def test_context_joint_human_preserves_provenance_trace_and_safe_warnings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    context_joint_human(
        {
            "request_id": "req_joint",
            "results": [
                {
                    "rank": 1,
                    "source": {
                        "schema": "public",
                        "table": "articles",
                        "id": "doc_\x1b[31m1",
                    },
                    "score": 0.016,
                    "introduced_by_graph": True,
                    "baseline_rank": None,
                    "rank_lift": None,
                    "graph": {"depth": 2},
                    "score_breakdown": {
                        "semantic": 0.01,
                        "lexical": 0.002,
                        "graph": 0.004,
                    },
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
            "warnings": [
                {
                    "code": "CONTEXT_GRAPH_CANDIDATES_UNMAPPED",
                    "message": "Some candidates were unmapped.",
                    "details": {"count": 3, "secret": "hidden"},
                }
            ],
        },
        verbose=True,
    )

    output = capsys.readouterr().out
    for value in (
        "public.articles:doc_\\x1b[31m1",
        "0.01000000",
        "INTRODUCED",
        "yes",
        "joint_weighted_rrf",
        "Semantic candidates",
        "Rescored candidates",
        "count=3",
        "Request ID: req_joint",
    ):
        assert value in output
    assert "secret" not in output
