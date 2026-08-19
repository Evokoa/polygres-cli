from __future__ import annotations

import sys
from typing import Any

from polygres_cli.cli_output import print_kv, print_table


def context_capabilities_human(payload: dict[str, Any], *, verbose: bool) -> None:
    rows = [
        ("Status", "pgContext Preview"),
        ("Setup", _availability(payload, "setup")),
        ("Dense search", _availability(payload, "dense_search")),
        ("Point scroll", _availability(payload, "point_scroll")),
        ("Count", _availability(payload, "count")),
        ("Facets", _availability(payload, "facets")),
        ("Grouped search", _availability(payload, "grouped_search")),
        ("Recall check", _availability(payload, "recall_check")),
        ("Text hybrid", _availability(payload, "text_hybrid")),
        ("Graph first", _availability(payload, "graph_first")),
        ("Vector first", _availability(payload, "vector_first")),
        ("Rank fusion", _availability(payload, "rank_fusion")),
        ("Joint", _availability(payload, "joint")),
        ("Max dimensions", payload.get("max_dimensions", "-")),
        ("Search limit", payload.get("max_search_limit", "-")),
        ("Reconcile batch", payload.get("max_reconcile_point_keys", "-")),
        ("Joint seed limit", payload.get("max_joint_seed_limit", "-")),
        ("Joint traversal limit", payload.get("max_joint_traversal_limit", "-")),
    ]
    if verbose:
        runtime = payload.get("runtime")
        if isinstance(runtime, dict):
            rows.append(("pgContext version", _display(runtime.get("pgcontext_version"))))
    print_kv(rows)
    for capability in (
        "setup",
        "dense_search",
        "point_scroll",
        "count",
        "facets",
        "grouped_search",
        "recall_check",
        "text_hybrid",
        "graph_first",
        "vector_first",
        "rank_fusion",
        "joint",
    ):
        blocker = payload.get(f"{capability}_blocker")
        if blocker and not payload.get(capability):
            message = payload.get(f"{capability}_blocker_message")
            if message:
                sys.stdout.write(f"{capability.replace('_', ' ').title()}: {_display(message)}\n")
            if verbose:
                sys.stdout.write(
                    f"{capability.replace('_', ' ').title()} blocker: {_display(blocker)}\n"
                )
    _request_id(payload, verbose)


def context_onboarding_human(payload: dict[str, Any], *, verbose: bool) -> None:
    candidates = _list(payload.get("candidates"))
    print_kv(
        [
            ("Status", _display(payload.get("status"))),
            ("Eligible pgvector sources", len(candidates)),
            ("Offer acknowledged", "Yes" if payload.get("offer_acknowledged") else "No"),
            ("Collection", _display(payload.get("completed_collection_id"))),
        ]
    )
    if candidates:
        sys.stdout.write("\n")
        print_table(
            [
                {
                    "ID": _display(item.get("vector_configuration_id")),
                    "NAME": _display(item.get("name")),
                    "SOURCE": (
                        f"{_display(item.get('schema_name'))}."
                        f"{_display(item.get('table_name'))}"
                    ),
                    "COLUMN": _display(item.get("embedding_column")),
                    "DIMENSIONS": _display(item.get("dimensions")),
                    "METRIC": _display(item.get("metric")),
                }
                for item in candidates
            ],
            ["ID", "NAME", "SOURCE", "COLUMN", "DIMENSIONS", "METRIC"],
        )
    _request_id(payload, verbose)


def context_discovery_human(payload: dict[str, Any], *, verbose: bool) -> None:
    rows: list[dict[str, Any]] = []
    for candidate in _list(payload.get("candidates")):
        source = _dict(candidate.get("source"))
        vectors = _list(candidate.get("vectors")) or [{}]
        reasons = _list(candidate.get("reasons"))
        reason = "; ".join(_display(item.get("message") or item.get("code")) for item in reasons)
        for vector in vectors:
            rows.append(
                {
                    "CLASS": _display(candidate.get("classification")),
                    "SOURCE": (
                        f"{_display(source.get('schema_name'))}."
                        f"{_display(source.get('table_name'))}"
                    ),
                    "KEY": _display(source.get("source_key_column")),
                    "KEY TYPE": _display(source.get("source_key_type")),
                    "VECTOR": _display(vector.get("column_name")),
                    "TYPE": _display(vector.get("type_owner")),
                    "DIMENSIONS": _display(vector.get("dimensions")),
                    "REASON": reason or "-",
                }
            )
    print_table(
        rows,
        ["CLASS", "SOURCE", "KEY", "KEY TYPE", "VECTOR", "TYPE", "DIMENSIONS", "REASON"],
    )
    _request_id(payload, verbose)


def context_preflight_human(
    payload: dict[str, Any],
    *,
    verbose: bool,
    quiet: bool,
) -> None:
    source = _dict(payload.get("source_identity"))
    print_kv(
        [
            ("Eligible", "Yes" if payload.get("eligible") else "No"),
            ("Classification", _display(payload.get("classification"))),
            (
                "Source",
                f"{_display(source.get('schema_name'))}.{_display(source.get('table_name'))}",
            ),
        ]
    )
    sys.stdout.write("\n")
    _checks_table(payload.get("checks"), name_key="code", include_code=False)
    if not quiet:
        actions = _list(payload.get("planned_actions"))
        if actions:
            sys.stdout.write("\nPlanned actions\n")
            for action in actions:
                ddl = action.get("ddl") or action.get("ddl_preview")
                label = action.get("action") or action.get("type") or "action"
                identity = action.get("object") or action.get("object_identity") or ""
                sys.stdout.write(f"{label} {identity}".rstrip() + "\n")
                if ddl:
                    sys.stdout.write(str(ddl).rstrip() + "\n")
    _request_id(payload, verbose)


def _default_collection_vector(collection: dict[str, Any]) -> dict[str, Any]:
    """Return the nested default vector with legacy flat-field fallback."""

    vectors = _list(collection.get("vectors"))
    default_name = collection.get("default_vector_name")
    for vector in vectors:
        if vector.get("is_default") or (
            default_name is not None and vector.get("name") == default_name
        ):
            return vector
    if vectors:
        return vectors[0]
    return {
        "column_name": collection.get("vector_column"),
        "dimensions": collection.get("dimensions"),
        "metric": collection.get("metric"),
        "index_name": collection.get("index_name"),
        "index_status": collection.get("index_status"),
    }


def context_collections_list_human(payload: dict[str, Any], *, verbose: bool) -> None:
    rows = []
    for collection in _list(payload.get("collections")):
        vector = _default_collection_vector(collection)
        rows.append(
            {
                "ID": _display(collection.get("id")),
                "NAME": _display(collection.get("name")),
                "SOURCE": (
                    f"{_display(collection.get('schema_name'))}."
                    f"{_display(collection.get('table_name'))}"
                ),
                "VECTOR": _display(vector.get("column_name")),
                "DIMENSIONS": _display(vector.get("dimensions")),
                "METRIC": _display(vector.get("metric")),
                "INDEX": _display(vector.get("index_status")),
                "POINTS": _display(collection.get("mapped_point_count")),
                "DEFAULT": "yes" if collection.get("is_default") else "no",
                "STATUS": _display(collection.get("status")),
            }
        )
    print_table(
        rows,
        [
            "ID",
            "NAME",
            "SOURCE",
            "VECTOR",
            "DIMENSIONS",
            "METRIC",
            "INDEX",
            "POINTS",
            "DEFAULT",
            "STATUS",
        ],
    )
    _pagination(payload)
    _request_id(payload, verbose)


def context_collection_get_human(payload: dict[str, Any], *, verbose: bool) -> None:
    collection = _dict(payload.get("collection"))
    vector = _default_collection_vector(collection)
    print_kv(
        [
            ("ID", _display(collection.get("id"))),
            ("Name", _display(collection.get("name"))),
            ("Status", _display(collection.get("status"))),
            ("Default", "yes" if collection.get("is_default") else "no"),
            (
                "Source",
                f"{_display(collection.get('schema_name'))}."
                f"{_display(collection.get('table_name'))}",
            ),
            ("Source key", _display(collection.get("source_key_column"))),
            ("Vector", _display(vector.get("column_name"))),
            ("Dimensions", _display(vector.get("dimensions"))),
            ("Metric", _display(vector.get("metric"))),
            ("Text column", _display(collection.get("text_column"))),
            ("Result columns", _join(collection.get("result_columns"))),
            ("Filter columns", _join(collection.get("filter_columns"))),
            ("Index", _display(vector.get("index_name"))),
            ("Index status", _display(vector.get("index_status"))),
            (
                "Point reconciliation",
                _display(collection.get("point_reconciliation_status")),
            ),
            ("Mapped points", _display(collection.get("mapped_point_count"))),
            ("Last reconciled", _display(collection.get("last_reconciled_at"))),
        ]
    )
    if verbose:
        plan = _dict(payload.get("deletion_plan"))
        if plan:
            sys.stdout.write("\n")
            context_deletion_plan_human(payload)
    _request_id(payload, verbose)


def context_collection_status_human(payload: dict[str, Any], *, verbose: bool) -> None:
    active = _dict(payload.get("active_operation"))
    print_kv(
        [
            ("Collection", _display(payload.get("collection_name"))),
            ("Status", _display(payload.get("status"))),
            ("Serving", _display(payload.get("serving_status"))),
            ("Index", _display(payload.get("index_status"))),
            ("Points", _display(payload.get("point_reconciliation_status"))),
            ("Mapped", _display(payload.get("mapped_point_count"))),
            ("Operation", _display(active.get("id"))),
            ("Updated", _display(payload.get("updated_at"))),
        ]
    )
    _request_id(payload, verbose)


def context_verification_human(payload: dict[str, Any], *, verbose: bool) -> None:
    print_kv(
        [
            ("Collection", _display(payload.get("collection_name"))),
            ("Verified", "yes" if payload.get("verified") else "no"),
            ("Checked", _display(payload.get("checked_at"))),
        ]
    )
    sys.stdout.write("\n")
    _checks_table(payload.get("checks"))
    _request_id(payload, verbose)


def context_diagnostics_human(payload: dict[str, Any], *, verbose: bool) -> None:
    print_kv(
        [
            ("Collection", _display(payload.get("collection_name"))),
            ("Overall", _display(payload.get("overall_status"))),
            ("Checked", _display(payload.get("checked_at"))),
        ]
    )
    sys.stdout.write("\n")
    _checks_table(payload.get("checks"))
    if verbose:
        actions = _list(payload.get("recommended_actions"))
        if actions:
            sys.stdout.write("\nRecommended actions\n")
            for action in actions:
                sys.stdout.write(
                    f"{_display(action.get('action'))}: {_display(action.get('message'))}\n"
                )
    _request_id(payload, verbose)


def context_deletion_plan_human(payload: dict[str, Any]) -> None:
    plan = _dict(payload.get("deletion_plan"))
    print_kv(
        [
            ("Drop pgContext collection", _display(plan.get("pgcontext_collection"))),
            ("Drop owned index", _display(plan.get("drop_owned_index"))),
            ("Preserve source table", _display(plan.get("preserve_source_table"))),
            ("Preserve source column", _display(plan.get("preserve_source_column"))),
            ("Preserve indexes", _join(plan.get("preserve_indexes"))),
        ]
    )


def context_filters_human(payload: dict[str, Any], *, verbose: bool) -> None:
    rows = []
    for item in _list(payload.get("filters")):
        path = _list(item.get("path"))
        source = _display(item.get("column"))
        if path:
            source += "." + ".".join(_display(segment) for segment in path)
        rows.append(
            {
                "KEY": _display(item.get("key")),
                "KIND": _display(item.get("kind")),
                "SOURCE": source,
            }
        )
    print_table(rows, ["KEY", "KIND", "SOURCE"])
    _request_id(payload, verbose)


def context_point_status_human(payload: dict[str, Any], *, verbose: bool) -> None:
    active = _dict(payload.get("active_operation"))
    print_kv(
        [
            ("Collection", _display(payload.get("collection_id"))),
            ("Status", _display(payload.get("status"))),
            ("Mapped", _display(payload.get("mapped_point_count"))),
            ("Last reconciled", _display(payload.get("last_reconciled_at"))),
            ("Error code", _display(payload.get("last_error_code"))),
            ("Error stage", _display(payload.get("last_error_stage"))),
            ("Operation", _display(active.get("id"))),
        ]
    )
    _request_id(payload, verbose)


def context_points_scroll_human(payload: dict[str, Any], *, verbose: bool) -> None:
    rows = [
        {"POINT ID": _display(item.get("point_id")), "SOURCE KEY": _display(item.get("source_key"))}
        for item in _list(payload.get("points"))
    ]
    print_table(rows, ["POINT ID", "SOURCE KEY"])
    _pagination(payload)
    _request_id(payload, verbose)


def context_point_mutation_human(payload: dict[str, Any], *, verbose: bool) -> None:
    print_kv(
        [
            ("Processed", payload.get("processed", 0)),
            ("Inserted", payload.get("inserted", 0)),
            ("Reactivated", payload.get("reactivated", 0)),
            ("Already active", payload.get("already_active", 0)),
            ("Deleted", payload.get("deleted", 0)),
            ("Already absent", payload.get("already_absent", 0)),
        ]
    )
    _request_id(payload, verbose)


def context_operations_list_human(payload: dict[str, Any], *, verbose: bool) -> None:
    rows = []
    for operation in _list(payload.get("operations")):
        rows.append(
            {
                "ID": _display(operation.get("id")),
                "KIND": _display(operation.get("kind")),
                "COLLECTION": _display(operation.get("collection_id")),
                "STATUS": _display(operation.get("status")),
                "STAGE": _display(operation.get("stage")),
                "PROCESSED": _display(operation.get("processed_units")),
                "TOTAL": _display(operation.get("total_units")),
                "ATTEMPTS": _display(operation.get("attempts")),
                "UPDATED": _display(operation.get("updated_at")),
            }
        )
    print_table(
        rows,
        [
            "ID",
            "KIND",
            "COLLECTION",
            "STATUS",
            "STAGE",
            "PROCESSED",
            "TOTAL",
            "ATTEMPTS",
            "UPDATED",
        ],
    )
    _pagination(payload)
    _request_id(payload, verbose)


def context_operation_human(
    payload: dict[str, Any],
    *,
    verbose: bool,
    idempotency_key: str | None = None,
) -> None:
    operation = _dict(payload.get("operation"))
    items: list[tuple[str, Any]] = [
        ("Operation", _display(operation.get("id"))),
        ("Kind", _display(operation.get("kind"))),
        ("Collection", _display(operation.get("collection_id"))),
        ("Status", _display(operation.get("status"))),
        ("Stage", _display(operation.get("stage"))),
        ("Processed", _display(operation.get("processed_units"))),
        ("Total", _display(operation.get("total_units"))),
        ("Attempts", _display(operation.get("attempts"))),
        ("Created", _display(operation.get("created_at"))),
        ("Started", _display(operation.get("started_at"))),
        ("Finished", _display(operation.get("finished_at"))),
        ("Updated", _display(operation.get("updated_at"))),
    ]
    result = operation.get("result") or operation.get("result_payload")
    if isinstance(result, dict):
        for label, key in (
            ("Result collection", "collection_id"),
            ("Scanned", "scanned"),
            ("Inserted", "inserted"),
            ("Reactivated", "reactivated"),
            ("Already active", "already_active"),
            ("Orphan deleted", "orphan_deleted"),
            ("Mapped points", "mapped_points"),
            ("Retry of", "retry_of"),
        ):
            if key in result:
                items.append((label, _display(result.get(key))))
    failure = _dict(operation.get("error"))
    if failure:
        items.extend(
            [
                ("Error code", _display(failure.get("code"))),
                ("Error message", _display(failure.get("message"))),
                ("Retryable", _display(failure.get("retryable"))),
            ]
        )
    if idempotency_key:
        items.append(("Idempotency key", idempotency_key))
    print_kv(items)
    _request_id(payload, verbose)


def context_count_human(payload: dict[str, Any], *, verbose: bool) -> None:
    print_kv([("Count", payload.get("count", 0))])
    _request_id(payload, verbose)


def context_facets_human(payload: dict[str, Any], *, verbose: bool) -> None:
    rows = [
        {"VALUE": _display(item.get("value")), "COUNT": _display(item.get("count"))}
        for item in _list(payload.get("facets"))
    ]
    print_table(rows, ["VALUE", "COUNT"])
    _request_id(payload, verbose)


def context_recall_human(payload: dict[str, Any], *, verbose: bool) -> None:
    print_kv(
        [
            ("Exact", payload.get("exact_count", 0)),
            ("Candidates", payload.get("candidate_count", 0)),
            ("Intersection", payload.get("intersection_count", 0)),
            ("Recall", _decimal(payload.get("recall"), 6)),
            ("Minimum", _decimal(payload.get("minimum_recall"), 6)),
            ("Status", _display(payload.get("status"))),
        ]
    )
    _request_id(payload, verbose)


def context_ranked_human(payload: dict[str, Any], *, verbose: bool) -> None:
    graph_mode = payload.get("mode") in {"graph_first", "vector_first", "rank_fusion"}
    grouped = any(
        "group_value" in result or "group_rank" in result
        for result in _list(payload.get("results"))
        if isinstance(result, dict)
    )
    rows = []
    for result in _list(payload.get("results")):
        source = _dict(result.get("source"))
        row = {
            "RANK": _display(result.get("rank")),
            "SOURCE": (
                f"{_display(source.get('schema'))}."
                f"{_display(source.get('table'))}:"
                f"{_display(source.get('id'))}"
            ),
            "SCORE": _decimal(result.get("score"), 8),
            "SCORE KIND": _display(result.get("score_kind")),
        }
        if grouped:
            row = {
                "GROUP": _display(result.get("group_value")),
                "GROUP RANK": _display(result.get("group_rank")),
                **row,
            }
        if graph_mode:
            context_lane = _dict(result.get("context"))
            graph_lane = _dict(result.get("graph"))
            row.update(
                {
                    "CONTEXT": _display(context_lane.get("rank")),
                    "GRAPH": _display(graph_lane.get("rank")),
                    "DEPTH": _display(graph_lane.get("depth")),
                }
            )
        rows.append(row)
    columns = ["RANK", "SOURCE", "SCORE", "SCORE KIND"]
    if grouped:
        columns = ["GROUP", "GROUP RANK", *columns]
    if graph_mode:
        columns.extend(["CONTEXT", "GRAPH", "DEPTH"])
    print_table(rows, columns)
    _ranked_warnings(payload)
    _request_id(payload, verbose)


def context_joint_human(payload: dict[str, Any], *, verbose: bool) -> None:
    rows = []
    for result in _list(payload.get("results")):
        source = _dict(result.get("source"))
        graph = _dict(result.get("graph"))
        breakdown = _dict(result.get("score_breakdown"))
        rows.append(
            {
                "RANK": _display(result.get("rank")),
                "SOURCE": (
                    f"{_display(source.get('schema'))}."
                    f"{_display(source.get('table'))}:"
                    f"{_display(source.get('id'))}"
                ),
                "SCORE": _decimal(result.get("score"), 8),
                "SEMANTIC": _decimal(breakdown.get("semantic"), 8),
                "LEXICAL": _decimal(breakdown.get("lexical"), 8),
                "GRAPH": _decimal(breakdown.get("graph"), 8),
                "INTRODUCED": _display(result.get("introduced_by_graph")),
                "BASELINE": _display(result.get("baseline_rank")),
                "LIFT": _display(result.get("rank_lift")),
                "DEPTH": _display(graph.get("depth")),
            }
        )
    print_table(
        rows,
        [
            "RANK",
            "SOURCE",
            "SCORE",
            "SEMANTIC",
            "LEXICAL",
            "GRAPH",
            "INTRODUCED",
            "BASELINE",
            "LIFT",
            "DEPTH",
        ],
    )
    if verbose:
        fusion = _dict(payload.get("fusion"))
        weights = _dict(fusion.get("weights"))
        trace = _dict(payload.get("trace"))
        print_kv(
            [
                ("Fusion", fusion.get("method")),
                ("RRF k", fusion.get("k")),
                ("Semantic weight", _decimal(weights.get("semantic"), 8)),
                ("Lexical weight", _decimal(weights.get("lexical"), 8)),
                ("Graph weight", _decimal(weights.get("graph"), 8)),
                ("Semantic candidates", trace.get("semantic_candidates")),
                ("Lexical candidates", trace.get("lexical_candidates")),
                ("Explicit seeds", trace.get("explicit_seeds")),
                ("Retrieval seeds", trace.get("retrieval_seeds")),
                ("Retained seeds", trace.get("retained_seeds")),
                ("Graph candidates", trace.get("graph_candidates")),
                ("Combined candidates", trace.get("combined_candidates")),
                ("Rescored candidates", trace.get("rescored_candidates")),
            ]
        )
    _ranked_warnings(payload)
    _request_id(payload, verbose)


def _ranked_warnings(payload: dict[str, Any]) -> None:
    for warning in _list(payload.get("warnings")):
        details = _dict(warning.get("details"))
        numeric = {
            key: value
            for key, value in details.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        suffix = ""
        if numeric:
            suffix = (
                " ("
                + ", ".join(f"{_display(key)}={_display(value)}" for key, value in numeric.items())
                + ")"
            )
        sys.stdout.write(
            f"Warning [{_display(warning.get('code'))}]: "
            f"{_display(warning.get('message'))}{suffix}\n"
        )


def context_wait_progress(
    operation: dict[str, Any],
    stage_changed: bool,
    count_changed: bool,
) -> None:
    if stage_changed:
        sys.stderr.write(
            f"Context operation {operation.get('id', '-')}: {operation.get('stage', '-')}\n"
        )
    if count_changed and operation.get("processed_units") is not None:
        total = operation.get("total_units")
        suffix = f" of {total}" if total is not None else ""
        sys.stderr.write(
            f"Context operation {operation.get('id', '-')}: "
            f"processed {operation.get('processed_units')}{suffix}\n"
        )


def _checks_table(
    value: object,
    *,
    name_key: str = "name",
    include_code: bool = True,
) -> None:
    rows = []
    for check in _list(value):
        rows.append(
            {
                "CHECK": _display(check.get(name_key)),
                "STATUS": _display(check.get("status")),
                "CODE": _display(check.get("code")),
                "MESSAGE": _display(check.get("message")),
            }
        )
    columns = ["CHECK", "STATUS", "CODE", "MESSAGE"]
    if not include_code:
        columns.remove("CODE")
    print_table(rows, columns)


def _availability(payload: dict[str, Any], field: str) -> str:
    return "Available" if payload.get(field) else "Unavailable"


def _pagination(payload: dict[str, Any]) -> None:
    if payload.get("has_more") and payload.get("next_cursor"):
        sys.stdout.write(f"Next cursor: {payload['next_cursor']}\n")


def _request_id(payload: dict[str, Any], verbose: bool) -> None:
    if verbose and payload.get("request_id"):
        sys.stdout.write(f"Request ID: {payload['request_id']}\n")


def _display(value: object) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return _terminal_text(str(value))


def _join(value: object) -> str:
    values = _list(value)
    return ", ".join(_display(item) for item in values) if values else "-"


def _terminal_text(value: str) -> str:
    parts: list[str] = []
    for character in value:
        codepoint = ord(character)
        if codepoint < 0x20 or 0x7F <= codepoint <= 0x9F:
            parts.append(f"\\x{codepoint:02x}")
        else:
            parts.append(character)
    return "".join(parts)


def _decimal(value: object, digits: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "-"
    return f"{value:.{digits}f}"


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
