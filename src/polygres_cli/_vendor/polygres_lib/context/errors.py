from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ContextErrorCode(str, Enum):
    REQUEST_INVALID = "CONTEXT_REQUEST_INVALID"
    IDENTIFIER_INVALID = "CONTEXT_IDENTIFIER_INVALID"
    SOURCE_INVALID = "CONTEXT_SOURCE_INVALID"
    DELETE_CONFIRMATION_INVALID = "CONTEXT_DELETE_CONFIRMATION_INVALID"
    POINT_KEY_INVALID = "CONTEXT_POINT_KEY_INVALID"
    EMBEDDING_INVALID = "CONTEXT_EMBEDDING_INVALID"
    FILTER_INVALID = "CONTEXT_FILTER_INVALID"
    LIMIT_EXCEEDED = "CONTEXT_LIMIT_EXCEEDED"
    GRAPH_START_REQUIRED = "CONTEXT_GRAPH_START_REQUIRED"
    GRAPH_DIRECTION_INVALID = "CONTEXT_GRAPH_DIRECTION_INVALID"
    RANKING_WEIGHTS_INVALID = "CONTEXT_RANKING_WEIGHTS_INVALID"
    RESOURCE_NAMESPACE_MISMATCH = "CONTEXT_RESOURCE_NAMESPACE_MISMATCH"
    COLLECTION_NOT_FOUND = "CONTEXT_COLLECTION_NOT_FOUND"
    OPERATION_NOT_FOUND = "CONTEXT_OPERATION_NOT_FOUND"
    COLLECTION_NOT_READY = "CONTEXT_COLLECTION_NOT_READY"
    TEXT_COLUMN_REQUIRED = "CONTEXT_TEXT_COLUMN_REQUIRED"
    GRAPH_NOT_READY = "CONTEXT_GRAPH_NOT_READY"
    SOURCE_KEY_ALIGNMENT_INVALID = "CONTEXT_SOURCE_KEY_ALIGNMENT_INVALID"
    CAPABILITY_UNAVAILABLE = "CONTEXT_CAPABILITY_UNAVAILABLE"
    SOURCE_KEY_NOT_FOUND = "CONTEXT_SOURCE_KEY_NOT_FOUND"
    SOURCE_VECTOR_INVALID = "CONTEXT_SOURCE_VECTOR_INVALID"
    FILTER_REGISTRATION_CONFLICT = "CONTEXT_FILTER_REGISTRATION_CONFLICT"
    POINT_CURSOR_INVALID = "CONTEXT_POINT_CURSOR_INVALID"
    RECALL_UNAVAILABLE = "CONTEXT_RECALL_UNAVAILABLE"
    COLLECTION_NAME_CONFLICT = "CONTEXT_COLLECTION_NAME_CONFLICT"
    PREFLIGHT_BLOCKED = "CONTEXT_PREFLIGHT_BLOCKED"
    OPERATION_CONFLICT = "CONTEXT_OPERATION_CONFLICT"
    IDEMPOTENCY_CONFLICT = "CONTEXT_IDEMPOTENCY_CONFLICT"
    OPERATION_NOT_CANCELLABLE = "CONTEXT_OPERATION_NOT_CANCELLABLE"
    OPERATION_NOT_RETRYABLE = "CONTEXT_OPERATION_NOT_RETRYABLE"
    OPERATION_CANCELLED = "CONTEXT_OPERATION_CANCELLED"
    ONBOARDING_NOT_ELIGIBLE = "CONTEXT_ONBOARDING_NOT_ELIGIBLE"
    ONBOARDING_NOT_AVAILABLE = "CONTEXT_ONBOARDING_NOT_AVAILABLE"
    RUNTIME_UNSUPPORTED = "CONTEXT_RUNTIME_UNSUPPORTED"
    EXTENSION_UNAVAILABLE = "CONTEXT_EXTENSION_UNAVAILABLE"
    SOURCE_TABLE_UNSUPPORTED = "CONTEXT_SOURCE_TABLE_UNSUPPORTED"
    SOURCE_KEY_REQUIRED = "CONTEXT_SOURCE_KEY_REQUIRED"
    SOURCE_KEY_TYPE_UNSUPPORTED = "CONTEXT_SOURCE_KEY_TYPE_UNSUPPORTED"
    SOURCE_KEY_TEXT_CONSTRAINT_REQUIRED = "CONTEXT_SOURCE_KEY_TEXT_CONSTRAINT_REQUIRED"
    SOURCE_PRIVILEGE_REQUIRED = "CONTEXT_SOURCE_PRIVILEGE_REQUIRED"
    VECTOR_COLUMN_MISSING = "CONTEXT_VECTOR_COLUMN_MISSING"
    VECTOR_COLUMN_CONFLICT = "CONTEXT_VECTOR_COLUMN_CONFLICT"
    VECTOR_TYPE_UNSUPPORTED = "CONTEXT_VECTOR_TYPE_UNSUPPORTED"
    VECTOR_NULLABLE = "CONTEXT_VECTOR_NULLABLE"
    VECTOR_DIMENSION_INVALID = "CONTEXT_VECTOR_DIMENSION_INVALID"
    COSINE_ZERO_VECTOR = "CONTEXT_COSINE_ZERO_VECTOR"
    RESULT_COLUMN_INVALID = "CONTEXT_RESULT_COLUMN_INVALID"
    FILTER_COLUMN_INVALID = "CONTEXT_FILTER_COLUMN_INVALID"
    JSONB_FILTER_PATH_INVALID = "CONTEXT_JSONB_FILTER_PATH_INVALID"
    RESERVED_FILTER_CONFLICT = "CONTEXT_RESERVED_FILTER_CONFLICT"
    TEXT_COLUMN_INVALID = "CONTEXT_TEXT_COLUMN_INVALID"
    HNSW_UNSUPPORTED = "CONTEXT_HNSW_UNSUPPORTED"
    INDEX_CONFLICT = "CONTEXT_INDEX_CONFLICT"
    MEMORY_PRESSURE = "CONTEXT_MEMORY_PRESSURE"
    PGVECTOR_SOURCE = "CONTEXT_PGVECTOR_SOURCE"
    UNSUPPORTED_VECTOR_TYPE = "CONTEXT_UNSUPPORTED_VECTOR_TYPE"


@dataclass(frozen=True, slots=True)
class ContextErrorDescriptor:
    status_code: int
    message: str
    safe_detail_fields: tuple[str, ...] = ()
    retryable: bool = False
    conflict: bool = False
    availability: bool = False


def _descriptor(
    status: int,
    message: str,
    *details: str,
    retryable: bool = False,
    conflict: bool = False,
    availability: bool = False,
) -> ContextErrorDescriptor:
    return ContextErrorDescriptor(
        status_code=status,
        message=message,
        safe_detail_fields=details,
        retryable=retryable,
        conflict=conflict,
        availability=availability,
    )


CONTEXT_ERROR_CATALOG: dict[ContextErrorCode, ContextErrorDescriptor] = {
    ContextErrorCode.REQUEST_INVALID: _descriptor(400, "Context request is invalid.", "field"),
    ContextErrorCode.IDENTIFIER_INVALID: _descriptor(
        400, "Context identifier is invalid.", "field"
    ),
    ContextErrorCode.SOURCE_INVALID: _descriptor(400, "Context source is invalid.", "field"),
    ContextErrorCode.DELETE_CONFIRMATION_INVALID: _descriptor(
        400, "Collection deletion confirmation is invalid.", "collection_id"
    ),
    ContextErrorCode.POINT_KEY_INVALID: _descriptor(
        400, "Context point key is invalid.", "field", "index"
    ),
    ContextErrorCode.EMBEDDING_INVALID: _descriptor(
        400,
        "Context embedding is invalid.",
        "expected_dimensions",
        "actual_dimensions",
    ),
    ContextErrorCode.FILTER_INVALID: _descriptor(
        400, "Context filter is invalid.", "field", "limit"
    ),
    ContextErrorCode.LIMIT_EXCEEDED: _descriptor(
        400, "Context request exceeds a limit.", "field", "limit"
    ),
    ContextErrorCode.GRAPH_START_REQUIRED: _descriptor(
        400, "A graph start entity is required.", "mode"
    ),
    ContextErrorCode.GRAPH_DIRECTION_INVALID: _descriptor(
        400, "Graph direction is invalid.", "direction"
    ),
    ContextErrorCode.RANKING_WEIGHTS_INVALID: _descriptor(
        400, "Rank-fusion weights are invalid.", "context_weight", "graph_weight"
    ),
    ContextErrorCode.RESOURCE_NAMESPACE_MISMATCH: _descriptor(
        400,
        "The resource belongs to another retrieval namespace.",
        "expected_namespace",
        "provided_namespace",
    ),
    ContextErrorCode.COLLECTION_NOT_FOUND: _descriptor(
        404, "Context collection was not found.", "collection"
    ),
    ContextErrorCode.OPERATION_NOT_FOUND: _descriptor(
        404, "Context operation was not found.", "operation_id"
    ),
    ContextErrorCode.COLLECTION_NOT_READY: _descriptor(
        409,
        "Context collection is not ready.",
        "collection_id",
        "status",
        conflict=True,
        availability=True,
    ),
    ContextErrorCode.TEXT_COLUMN_REQUIRED: _descriptor(
        409,
        "The collection does not have a configured text column.",
        "collection_id",
        conflict=True,
        availability=True,
    ),
    ContextErrorCode.GRAPH_NOT_READY: _descriptor(
        409,
        "Graph retrieval is not ready.",
        "graph_status",
        conflict=True,
        availability=True,
    ),
    ContextErrorCode.SOURCE_KEY_ALIGNMENT_INVALID: _descriptor(
        409,
        "Context and graph source identities do not align.",
        "collection_id",
        "reason",
        conflict=True,
    ),
    ContextErrorCode.CAPABILITY_UNAVAILABLE: _descriptor(
        409,
        "Context capability is unavailable.",
        "capability",
        "blocker",
        conflict=True,
        availability=True,
    ),
    ContextErrorCode.SOURCE_KEY_NOT_FOUND: _descriptor(
        409,
        "One or more source keys were not found.",
        "collection_id",
        "count",
        conflict=True,
    ),
    ContextErrorCode.SOURCE_VECTOR_INVALID: _descriptor(
        409,
        "One or more source vectors are invalid.",
        "collection_id",
        "count",
        "reason",
        conflict=True,
    ),
    ContextErrorCode.FILTER_REGISTRATION_CONFLICT: _descriptor(
        409,
        "The filter key is already registered to a different source.",
        "collection_id",
        "key",
        conflict=True,
    ),
    ContextErrorCode.POINT_CURSOR_INVALID: _descriptor(400, "Point cursor is invalid.", "field"),
    ContextErrorCode.RECALL_UNAVAILABLE: _descriptor(
        409,
        "Recall checking is unavailable for this collection.",
        "collection_id",
        "reason",
        conflict=True,
        availability=True,
    ),
    ContextErrorCode.COLLECTION_NAME_CONFLICT: _descriptor(
        409, "Context collection name is already in use.", "name", conflict=True
    ),
    ContextErrorCode.PREFLIGHT_BLOCKED: _descriptor(
        409,
        "Context preflight blocked collection creation.",
        "blocker",
        "field",
        conflict=True,
    ),
    ContextErrorCode.OPERATION_CONFLICT: _descriptor(
        409,
        "Another Context operation owns this resource.",
        "operation_id",
        "collection_id",
        conflict=True,
        retryable=True,
    ),
    ContextErrorCode.IDEMPOTENCY_CONFLICT: _descriptor(
        409,
        "Idempotency key was used for a different request.",
        "field",
        conflict=True,
    ),
    ContextErrorCode.OPERATION_NOT_CANCELLABLE: _descriptor(
        409,
        "Context operation cannot be cancelled.",
        "operation_id",
        "status",
        conflict=True,
    ),
    ContextErrorCode.OPERATION_NOT_RETRYABLE: _descriptor(
        409,
        "Context operation cannot be retried.",
        "operation_id",
        "status",
        conflict=True,
    ),
    ContextErrorCode.OPERATION_CANCELLED: _descriptor(
        409, "Context operation was cancelled.", "operation_id", conflict=True
    ),
}

for _code in ContextErrorCode:
    CONTEXT_ERROR_CATALOG.setdefault(
        _code,
        _descriptor(
            409,
            _code.value.replace("CONTEXT_", "").replace("_", " ").capitalize() + ".",
            "field",
            conflict=True,
        ),
    )


__all__ = [
    "CONTEXT_ERROR_CATALOG",
    "ContextErrorCode",
    "ContextErrorDescriptor",
]
