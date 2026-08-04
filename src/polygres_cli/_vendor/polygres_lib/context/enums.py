from enum import Enum


class ContextCapability(str, Enum):
    SETUP = "setup"
    DENSE_SEARCH = "dense_search"
    POINT_SCROLL = "point_scroll"
    COUNT = "count"
    FACETS = "facets"
    GROUPED_SEARCH = "grouped_search"
    RECALL_CHECK = "recall_check"
    TEXT_HYBRID = "text_hybrid"
    GRAPH_FIRST = "graph_first"
    VECTOR_FIRST = "vector_first"
    RANK_FUSION = "rank_fusion"
    JOINT = "joint"


class ContextCollectionStatus(str, Enum):
    READY = "ready"
    STALE = "stale"
    FAILED = "failed"
    DELETING = "deleting"


class ContextServingStatus(str, Enum):
    AVAILABLE = "available"
    BLOCKED = "blocked"


class ContextIndexStatus(str, Enum):
    MISSING = "missing"
    CREATING = "creating"
    READY = "ready"
    STALE = "stale"
    FAILED = "failed"


class ContextPointReconciliationStatus(str, Enum):
    PENDING = "pending"
    RECONCILING = "reconciling"
    CURRENT = "current"
    STALE = "stale"
    FAILED = "failed"


class ContextSourceClassification(str, Enum):
    READY_TO_CONFIGURE = "ready_to_configure"
    NEEDS_SETUP = "needs_setup"
    UNSUPPORTED = "unsupported"
    VECTOR_SOURCE = "vector_source"


class ContextSourceMode(str, Enum):
    EXISTING = "existing"
    ADD_COLUMN = "add_column"
    NEW_TABLE = "new_table"


class ContextMetric(str, Enum):
    COSINE = "cosine"
    INNER_PRODUCT = "inner_product"
    L2 = "l2"
    L1 = "l1"


class ContextIndexKind(str, Enum):
    NONE = "none"
    HNSW = "hnsw"


class ContextFilterKind(str, Enum):
    COLUMN = "column"
    JSONB_PATH = "jsonb_path"


class ContextOperationKind(str, Enum):
    COLLECTION_CREATE = "collection_create"
    COLLECTION_SET_DEFAULT = "collection_set_default"
    COLLECTION_UPDATE = "collection_update"
    COLLECTION_DELETE = "collection_delete"
    COLLECTION_REINDEX = "collection_reindex"
    FILTER_ADD_COLUMN = "filter_add_column"
    FILTER_ADD_JSONB_PATH = "filter_add_jsonb_path"
    POINTS_UPSERT = "points_upsert"
    POINTS_DELETE = "points_delete"
    POINTS_RECONCILE = "points_reconcile"


class ContextOperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContextRankedMode(str, Enum):
    DENSE = "dense"
    TEXT_HYBRID = "text_hybrid"
    GRAPH_FIRST = "graph_first"
    VECTOR_FIRST = "vector_first"
    RANK_FUSION = "rank_fusion"
    JOINT = "joint"


class ContextScoreKind(str, Enum):
    CONTEXT_METRIC = "context_metric"
    RRF = "rrf"
    WEIGHTED_RRF = "weighted_rrf"
    JOINT_WEIGHTED_RRF = "joint_weighted_rrf"


class ContextDiagnosticStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class ContextDiagnosticCheckStatus(str, Enum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    SKIPPED = "skipped"


class ContextVerificationCheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


class ContextRecallStatus(str, Enum):
    PASSING = "passing"
    FAILING = "failing"
    EMPTY_EXACT = "empty_exact"


class ContextGraphDirection(str, Enum):
    OUT = "out"
    IN = "in"
    ANY = "any"
    BOTH = "both"


class ContextRecommendedAction(str, Enum):
    POINTS_RECONCILE = "points_reconcile"
    COLLECTION_REINDEX = "collection_reindex"
    REPAIR_SOURCE = "repair_source"
    REPAIR_PERMISSIONS = "repair_permissions"
    RECREATE_COLLECTION = "recreate_collection"
    CONTACT_SUPPORT = "contact_support"


CONTEXT_OPERATION_STAGES: dict[ContextOperationKind, tuple[str, ...]] = {
    ContextOperationKind.COLLECTION_CREATE: (
        "queued",
        "preflight",
        "creating_source_objects",
        "creating_collection",
        "registering_vector",
        "registering_filters",
        "syncing_points",
        "reconciling_points",
        "building_index",
        "attaching_index",
        "verifying",
        "ready",
        "failed",
        "cancelled",
    ),
    ContextOperationKind.COLLECTION_UPDATE: (
        "queued",
        "validating_config",
        "updating_config",
        "verifying",
        "ready",
        "failed",
        "cancelled",
    ),
    ContextOperationKind.COLLECTION_SET_DEFAULT: (
        "queued",
        "setting_default",
        "verifying",
        "ready",
        "failed",
        "cancelled",
    ),
    ContextOperationKind.COLLECTION_DELETE: (
        "queued",
        "verifying_ownership",
        "dropping_index",
        "dropping_collection",
        "deleting_record",
        "deleted",
        "failed",
        "cancelled",
    ),
    ContextOperationKind.COLLECTION_REINDEX: (
        "queued",
        "preflight",
        "building_index",
        "attaching_index",
        "verifying",
        "ready",
        "failed",
        "cancelled",
    ),
    ContextOperationKind.FILTER_ADD_COLUMN: (
        "queued",
        "validating_filter",
        "registering_filter",
        "verifying",
        "ready",
        "failed",
        "cancelled",
    ),
    ContextOperationKind.FILTER_ADD_JSONB_PATH: (
        "queued",
        "validating_filter",
        "registering_filter",
        "verifying",
        "ready",
        "failed",
        "cancelled",
    ),
    ContextOperationKind.POINTS_UPSERT: (
        "queued",
        "validating_points",
        "upserting_points",
        "complete",
        "failed",
        "cancelled",
    ),
    ContextOperationKind.POINTS_DELETE: (
        "queued",
        "validating_points",
        "deleting_points",
        "complete",
        "failed",
        "cancelled",
    ),
    ContextOperationKind.POINTS_RECONCILE: (
        "queued",
        "scanning_source",
        "upserting_points",
        "reconciling_points",
        "verifying",
        "current",
        "failed",
        "cancelled",
    ),
}


__all__ = [
    "CONTEXT_OPERATION_STAGES",
    "ContextCapability",
    "ContextCollectionStatus",
    "ContextDiagnosticCheckStatus",
    "ContextDiagnosticStatus",
    "ContextFilterKind",
    "ContextGraphDirection",
    "ContextIndexKind",
    "ContextIndexStatus",
    "ContextMetric",
    "ContextOperationKind",
    "ContextOperationStatus",
    "ContextPointReconciliationStatus",
    "ContextRankedMode",
    "ContextRecallStatus",
    "ContextRecommendedAction",
    "ContextScoreKind",
    "ContextServingStatus",
    "ContextSourceClassification",
    "ContextSourceMode",
    "ContextVerificationCheckStatus",
]
