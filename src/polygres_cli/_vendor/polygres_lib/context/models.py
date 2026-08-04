from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import (
    ContextCollectionStatus,
    ContextDiagnosticCheckStatus,
    ContextDiagnosticStatus,
    ContextFilterKind,
    ContextGraphDirection,
    ContextIndexKind,
    ContextIndexStatus,
    ContextMetric,
    ContextOperationKind,
    ContextOperationStatus,
    ContextPointReconciliationStatus,
    ContextRankedMode,
    ContextRecallStatus,
    ContextRecommendedAction,
    ContextScoreKind,
    ContextServingStatus,
    ContextSourceClassification,
    ContextSourceMode,
    ContextVerificationCheckStatus,
)
from .validation import (
    MAX_GRAPH_DEPTH,
    MAX_JOINT_SEEDS,
    MAX_JOINT_TRAVERSAL,
    MAX_POINT_KEYS,
    MAX_RANKED_LIMIT,
    RESERVED_SOURCE_FILTER_KEY,
    deduplicate_first,
    normalize_joint_weights,
    require_valid,
    validate_embedding,
    validate_filter,
    validate_identifier,
    validate_joint_weights,
    validate_rank_fusion_weights,
    validate_recall_threshold,
    validate_source_key,
    validate_source_keys,
)


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextResponse(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    def to_dict(self) -> dict[str, Any]:
        """Return the public JSON representation, including additive fields."""
        return self.model_dump(mode="json", by_alias=True)


class EmptyRequest(ContextRequest):
    pass


class DiscoveryRequest(ContextRequest):
    schema_names: list[str] | None = None

    @field_validator("schema_names")
    @classmethod
    def _schemas(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if not value:
            raise ValueError("schema_names must not be empty")
        for index, item in enumerate(value):
            require_valid(validate_identifier(item, field=f"schema_names.{index}"))
        return deduplicate_first(value)


class ContextSourceRequest(ContextRequest):
    mode: ContextSourceMode
    schema_name: str
    table_name: str
    source_key_column: Literal["id"] = "id"
    content_column: str | None = None
    metadata_column: str | None = None

    @field_validator("schema_name", "table_name", "content_column", "metadata_column")
    @classmethod
    def _identifier(cls, value: str | None, info) -> str | None:
        if value is not None:
            require_valid(validate_identifier(value, field=info.field_name))
        return value

    @model_validator(mode="after")
    def _mode_shape(self) -> ContextSourceRequest:
        if self.mode is not ContextSourceMode.NEW_TABLE and (
            self.content_column is not None or self.metadata_column is not None
        ):
            raise ValueError("content_column and metadata_column require new_table")
        return self


class ContextVectorRequest(ContextRequest):
    column_name: str = "embedding"
    dimensions: int = Field(ge=1, le=16_000)
    metric: ContextMetric = ContextMetric.COSINE

    @field_validator("column_name")
    @classmethod
    def _column(cls, value: str) -> str:
        require_valid(validate_identifier(value, field="column_name"))
        return value


class JsonbFilterPathRequest(ContextRequest):
    key: str
    column: str
    path: list[str] = Field(min_length=1, max_length=16)

    @field_validator("key", "column")
    @classmethod
    def _identifier(cls, value: str, info) -> str:
        require_valid(validate_identifier(value, field=info.field_name))
        if info.field_name == "key" and value == RESERVED_SOURCE_FILTER_KEY:
            raise ValueError("reserved filter key")
        return value

    @field_validator("path")
    @classmethod
    def _path(cls, value: list[str]) -> list[str]:
        for index, segment in enumerate(value):
            if not segment or "\x00" in segment or len(segment.encode("utf-8")) > 512:
                raise ValueError(f"path.{index} is invalid")
        return value


class CollectionCreateRequest(ContextRequest):
    name: str
    source: ContextSourceRequest
    vector: ContextVectorRequest
    text_column: str | None = None
    result_columns: list[str] = Field(default_factory=list, max_length=32)
    filter_columns: list[str] = Field(default_factory=list, max_length=32)
    jsonb_filter_paths: list[JsonbFilterPathRequest] = Field(default_factory=list, max_length=32)
    index_kind: ContextIndexKind = ContextIndexKind.HNSW
    max_search_limit: int = Field(default=1_000, ge=1, le=1_000)

    @field_validator("name", "text_column")
    @classmethod
    def _identifier(cls, value: str | None, info) -> str | None:
        if value is not None:
            require_valid(validate_identifier(value, field=info.field_name))
        return value

    @field_validator("result_columns", "filter_columns")
    @classmethod
    def _columns(cls, value: list[str], info) -> list[str]:
        unique = deduplicate_first(value)
        if len(unique) != len(value):
            raise ValueError(f"{info.field_name} contains duplicates")
        for index, item in enumerate(value):
            require_valid(validate_identifier(item, field=f"{info.field_name}.{index}"))
            if item == RESERVED_SOURCE_FILTER_KEY:
                raise ValueError("reserved source filter key")
        return value

    @model_validator(mode="after")
    def _filter_keys(self) -> CollectionCreateRequest:
        keys = [*self.filter_columns, *(item.key for item in self.jsonb_filter_paths)]
        if len(keys) != len(set(keys)):
            raise ValueError("filter keys must be unique")
        return self


class CollectionSetDefaultRequest(ContextRequest):
    is_default: Literal[True]


class CollectionUpdateRequest(ContextRequest):
    text_column: str | None = None
    result_columns: list[str] | None = Field(default=None, max_length=32)
    max_search_limit: int | None = Field(default=None, ge=1, le=1_000)

    @field_validator("text_column")
    @classmethod
    def _text_column(cls, value: str | None) -> str | None:
        if value is not None:
            require_valid(validate_identifier(value, field="text_column"))
        return value

    @field_validator("result_columns")
    @classmethod
    def _result_columns(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if len(value) != len(set(value)):
            raise ValueError("result_columns contains duplicates")
        for index, item in enumerate(value):
            require_valid(validate_identifier(item, field=f"result_columns.{index}"))
        return value

    @model_validator(mode="after")
    def _at_least_one(self) -> CollectionUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("at least one logical field is required")
        return self


class CollectionDeleteRequest(ContextRequest):
    confirm_collection_id: UUID


class FilterColumnRequest(ContextRequest):
    key: str
    column: str

    @field_validator("key", "column")
    @classmethod
    def _identifier(cls, value: str, info) -> str:
        require_valid(validate_identifier(value, field=info.field_name))
        if info.field_name == "key" and value == RESERVED_SOURCE_FILTER_KEY:
            raise ValueError("reserved filter key")
        return value


class FilterJsonbPathRequest(FilterColumnRequest):
    path: list[str] = Field(min_length=1, max_length=16)

    @field_validator("path")
    @classmethod
    def _path(cls, value: list[str]) -> list[str]:
        return JsonbFilterPathRequest(key="synthetic", column="synthetic", path=value).path


class PointKeysRequest(ContextRequest):
    source_keys: list[str] = Field(min_length=1, max_length=MAX_POINT_KEYS)

    @field_validator("source_keys")
    @classmethod
    def _keys(cls, value: list[str]) -> list[str]:
        normalized, violations = validate_source_keys(value)
        require_valid(violations)
        return normalized


class CountRequest(ContextRequest):
    collection: str
    filter: dict[str, Any] | None = None

    @field_validator("filter")
    @classmethod
    def _filter(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        require_valid(validate_filter(value))
        return value


class FacetsRequest(CountRequest):
    field: str
    limit: int = Field(default=10, ge=1, le=MAX_RANKED_LIMIT)

    @field_validator("field")
    @classmethod
    def _field(cls, value: str) -> str:
        require_valid(validate_identifier(value, field="field"))
        return value


class DenseSearchRequest(CountRequest):
    embedding: list[float]
    limit: int = Field(default=10, ge=1, le=MAX_RANKED_LIMIT)

    @field_validator("embedding", mode="before")
    @classmethod
    def _embedding(cls, value: list[float]) -> list[float]:
        require_valid(validate_embedding(value))
        return value


class GroupedSearchRequest(ContextRequest):
    collection: str
    embedding: list[float]
    group_by: str
    group_limit: int = Field(default=1, ge=1, le=MAX_RANKED_LIMIT)
    limit: int = Field(default=10, ge=1, le=MAX_RANKED_LIMIT)

    @field_validator("embedding", mode="before")
    @classmethod
    def _embedding(cls, value: list[float]) -> list[float]:
        require_valid(validate_embedding(value))
        return value

    @field_validator("group_by")
    @classmethod
    def _group(cls, value: str) -> str:
        require_valid(validate_identifier(value, field="group_by"))
        return value


class RecallCheckRequest(DenseSearchRequest):
    minimum_recall: float = 0.95

    @field_validator("minimum_recall")
    @classmethod
    def _recall(cls, value: float) -> float:
        require_valid(validate_recall_threshold(value))
        return value


class TextHybridSearchRequest(ContextRequest):
    collection: str
    embedding: list[float]
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=MAX_RANKED_LIMIT)

    @field_validator("embedding", mode="before")
    @classmethod
    def _embedding(cls, value: list[float]) -> list[float]:
        require_valid(validate_embedding(value))
        return value


class GraphStart(ContextRequest):
    schema_name: str = Field(alias="schema")
    table: str
    id: str = Field(min_length=1, max_length=1_024)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @field_validator("schema_name", "table")
    @classmethod
    def _identifier(cls, value: str, info) -> str:
        require_valid(validate_identifier(value, field=info.field_name))
        return value

    @field_validator("id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        require_valid(validate_source_key(value, field="id"))
        return value


class GraphSearchBase(DenseSearchRequest):
    max_depth: int = Field(default=2, ge=1, le=MAX_GRAPH_DEPTH)
    graph_limit: int = Field(default=200, ge=1, le=MAX_RANKED_LIMIT)
    relationship_types: list[str] = Field(default_factory=list, max_length=32)
    direction: ContextGraphDirection = ContextGraphDirection.ANY

    @field_validator("relationship_types")
    @classmethod
    def _relationships(cls, value: list[str]) -> list[str]:
        unique = deduplicate_first(value)
        for index, item in enumerate(unique):
            require_valid(validate_identifier(item, field=f"relationship_types.{index}"))
        return unique


class GraphFirstSearchRequest(GraphSearchBase):
    start: GraphStart


class VectorFirstSearchRequest(GraphSearchBase):
    context_limit: int = Field(default=50, ge=1, le=MAX_RANKED_LIMIT)


class RankFusionWeights(ContextRequest):
    context: float = 0.7
    graph: float = 0.3

    @model_validator(mode="after")
    def _weights(self) -> RankFusionWeights:
        require_valid(validate_rank_fusion_weights(self.context, self.graph))
        return self


class RankFusionSearchRequest(GraphSearchBase):
    start: GraphStart
    context_limit: int = Field(default=50, ge=1, le=MAX_RANKED_LIMIT)
    weights: RankFusionWeights = Field(default_factory=RankFusionWeights)


class JointWeights(ContextRequest):
    semantic: float = 0.7
    lexical: float = 0.0
    graph: float = 0.3

    @model_validator(mode="before")
    @classmethod
    def _raw_weights(cls, value: Any) -> Any:
        if isinstance(value, dict):
            require_valid(
                validate_joint_weights(
                    value.get("semantic", 0.7),
                    value.get("lexical", 0.0),
                    value.get("graph", 0.3),
                )
            )
        return value

    @model_validator(mode="after")
    def _weights(self) -> JointWeights:
        require_valid(validate_joint_weights(self.semantic, self.lexical, self.graph))
        return self

    def normalized(self) -> tuple[float, float, float]:
        return normalize_joint_weights(self.semantic, self.lexical, self.graph)


class JointSearchRequest(GraphSearchBase):
    embedding: list[float]
    query: str | None = None
    starts: list[GraphStart] = Field(default_factory=list, max_length=MAX_JOINT_SEEDS)
    context_limit: int = Field(default=50, ge=1, le=MAX_RANKED_LIMIT)
    seed_limit: int = Field(default=8, ge=1, le=MAX_JOINT_SEEDS)
    traversal_limit: int = Field(default=500, ge=1, le=MAX_JOINT_TRAVERSAL)
    weights: JointWeights = Field(default_factory=JointWeights)

    @field_validator("embedding", mode="before")
    @classmethod
    def _raw_embedding(cls, value: Any) -> Any:
        require_valid(validate_embedding(value))
        return value

    @field_validator(
        "max_depth",
        "context_limit",
        "seed_limit",
        "graph_limit",
        "traversal_limit",
        "limit",
        mode="before",
    )
    @classmethod
    def _strict_limits(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("limit must be an integer")
        return value

    @field_validator("query")
    @classmethod
    def _query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped

    @field_validator("starts")
    @classmethod
    def _starts(cls, value: list[GraphStart]) -> list[GraphStart]:
        seen: set[tuple[str, str, str]] = set()
        output = []
        for start in value:
            identity = (start.schema_name, start.table, start.id)
            if identity not in seen:
                seen.add(identity)
                output.append(start)
        return output

    @model_validator(mode="after")
    def _lexical_query(self) -> JointSearchRequest:
        if self.weights.lexical > 0 and self.query is None:
            raise ValueError("query is required when weights.lexical is positive")
        return self


class ErrorBody(ContextResponse):
    code: str
    message: str
    details: dict[str, Any]


class ErrorEnvelope(ContextResponse):
    request_id: str
    error: ErrorBody


class RuntimeCapabilities(ContextResponse):
    postgres_major: int
    pgcontext_version: str | None
    pgcontext_source_commit: str | None
    pgvector_installed: bool
    pgcontext_installed: bool


class CapabilitiesResponse(ContextResponse):
    request_id: str
    contract_version: Literal["context.v1"]
    product_status: Literal["preview"]
    runtime: RuntimeCapabilities
    setup: bool
    setup_blocker: str | None
    setup_blocker_message: str | None = None
    dense_search: bool
    dense_search_blocker: str | None
    dense_search_blocker_message: str | None = None
    point_scroll: bool
    point_scroll_blocker: str | None
    point_scroll_blocker_message: str | None = None
    count: bool
    count_blocker: str | None
    count_blocker_message: str | None = None
    facets: bool
    facets_blocker: str | None
    facets_blocker_message: str | None = None
    grouped_search: bool
    grouped_search_blocker: str | None
    grouped_search_blocker_message: str | None = None
    recall_check: bool
    recall_check_blocker: str | None
    recall_check_blocker_message: str | None = None
    text_hybrid: bool
    text_hybrid_blocker: str | None
    text_hybrid_blocker_message: str | None = None
    graph_first: bool
    graph_first_blocker: str | None
    graph_first_blocker_message: str | None = None
    vector_first: bool
    vector_first_blocker: str | None
    vector_first_blocker_message: str | None = None
    rank_fusion: bool
    rank_fusion_blocker: str | None
    rank_fusion_blocker_message: str | None = None
    joint: bool
    joint_blocker: str | None
    joint_blocker_message: str | None = None
    ranked_search_cursor: Literal[False]
    max_dimensions: int
    max_search_limit: int
    max_context_limit: int
    max_graph_limit: int
    max_joint_seed_limit: int
    max_joint_traversal_limit: int
    max_graph_depth: int
    max_relationship_types: int
    max_result_columns: int
    max_filter_bytes: int
    max_filter_depth: int
    max_filter_nodes: int
    max_filter_values: int
    max_values_per_match: int
    max_reconcile_point_keys: int
    max_point_keys_per_operation: int


class DiscoveryReason(ContextResponse):
    code: str
    message: str
    field: str | None = None


class DiscoverySource(ContextResponse):
    schema_name: str
    table_name: str
    source_key_column: str
    source_key_type: str


class DiscoveryVector(ContextResponse):
    column_name: str
    type_owner: str
    dimensions: int | None
    nullable: bool


class DiscoveryCandidate(ContextResponse):
    classification: ContextSourceClassification | str
    source: DiscoverySource
    vectors: list[DiscoveryVector]
    reasons: list[DiscoveryReason]


class DiscoveryResponse(ContextResponse):
    request_id: str
    candidates: list[DiscoveryCandidate]


class PreflightCheck(ContextResponse):
    code: str
    status: str
    message: str


class PreflightBlocker(ContextResponse):
    code: str
    message: str
    field: str | None = None


class PreflightOwnership(ContextResponse):
    source_table: str
    vector_column: str
    index: str


class PreflightResponse(ContextResponse):
    request_id: str
    eligible: bool
    classification: ContextSourceClassification | str
    normalized_request: dict[str, Any]
    source_identity: dict[str, str]
    checks: list[PreflightCheck]
    blockers: list[PreflightBlocker]
    warnings: list[dict[str, Any]]
    planned_actions: list[dict[str, Any]]
    ownership: PreflightOwnership


class ContextCollection(ContextResponse):
    id: UUID
    project_id: str
    name: str
    is_default: bool
    status: ContextCollectionStatus | str
    schema_name: str
    table_name: str
    source_key_column: str
    source_key_type: str
    source_mode: ContextSourceMode
    owns_source_table: bool
    owns_vector_column: bool
    vector_name: str
    vector_column: str
    dimensions: int
    metric: ContextMetric
    max_search_limit: int
    text_column: str | None
    result_columns: list[str]
    filter_columns: list[str]
    jsonb_filter_paths: list[dict[str, Any]]
    index_kind: ContextIndexKind
    index_name: str | None
    owns_index: bool
    index_status: ContextIndexStatus | str
    point_reconciliation_status: ContextPointReconciliationStatus | str
    mapped_point_count: int | None
    last_reconciled_at: datetime | None
    last_error_code: str | None
    last_error_stage: str | None
    created_at: datetime
    updated_at: datetime


class CollectionListResponse(ContextResponse):
    request_id: str
    collections: list[ContextCollection]
    next_cursor: str | None
    has_more: bool


class DeletionPlan(ContextResponse):
    pgcontext_collection: str
    drop_owned_index: str | None
    preserve_source_table: str
    preserve_source_column: str
    preserve_indexes: list[str]


class CollectionGetResponse(ContextResponse):
    request_id: str
    collection: ContextCollection
    deletion_plan: DeletionPlan


class ContextOperationFailure(ContextResponse):
    code: str
    message: str
    details: dict[str, Any]
    http_status: int


class ContextOperation(ContextResponse):
    id: UUID
    collection_id: UUID | None
    kind: ContextOperationKind
    status: ContextOperationStatus | str
    stage: str
    processed_units: int
    total_units: int | None
    attempts: int
    retry_until: datetime
    error: ContextOperationFailure | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class OperationEnvelope(ContextResponse):
    request_id: str
    operation: ContextOperation


class OperationListResponse(ContextResponse):
    request_id: str
    operations: list[ContextOperation]
    next_cursor: str | None
    has_more: bool


class CollectionStatusResponse(ContextResponse):
    request_id: str
    collection_id: UUID
    collection_name: str
    status: ContextCollectionStatus | str
    serving_status: ContextServingStatus | str
    index_status: ContextIndexStatus | str
    point_reconciliation_status: ContextPointReconciliationStatus | str
    mapped_point_count: int | None
    last_reconciled_at: datetime | None
    active_operation: ContextOperation | None
    last_error_code: str | None
    last_error_stage: str | None
    updated_at: datetime


class VerificationCheck(ContextResponse):
    name: str
    status: ContextVerificationCheckStatus | str
    code: str | None
    message: str


class VerificationResponse(ContextResponse):
    request_id: str
    collection_id: UUID
    collection_name: str
    verified: bool
    checked_at: datetime
    checks: list[VerificationCheck]


class DiagnosticCheck(ContextResponse):
    name: str
    status: ContextDiagnosticCheckStatus | str
    code: str | None
    message: str
    expected: str | None
    actual: str | None
    count: int | None


class RecommendedAction(ContextResponse):
    action: ContextRecommendedAction
    message: str


class DiagnosticsResponse(ContextResponse):
    request_id: str
    collection_id: UUID
    collection_name: str
    overall_status: ContextDiagnosticStatus | str
    checked_at: datetime
    checks: list[DiagnosticCheck]
    recommended_actions: list[RecommendedAction]


class FilterRegistration(ContextResponse):
    key: str
    kind: ContextFilterKind
    column: str
    path: list[str] | None


class FilterListResponse(ContextResponse):
    request_id: str
    collection_id: UUID
    filters: list[FilterRegistration]


class PointStatusResponse(ContextResponse):
    request_id: str
    collection_id: UUID
    status: ContextPointReconciliationStatus | str
    mapped_point_count: int | None
    last_reconciled_at: datetime | None
    last_error_code: str | None
    last_error_stage: str | None
    active_operation: ContextOperation | None


class PointMapping(ContextResponse):
    point_id: int
    source_key: str


class PointScrollResponse(ContextResponse):
    request_id: str
    collection_id: UUID
    points: list[PointMapping]
    next_cursor: str | None
    has_more: bool


class PointMutationResponse(ContextResponse):
    request_id: str
    collection_id: UUID
    processed: int
    inserted: int
    reactivated: int
    already_active: int
    deleted: int
    already_absent: int


class CountResponse(ContextResponse):
    request_id: str
    collection_id: UUID
    collection_name: str
    count: int


class FacetValue(ContextResponse):
    value: str
    count: int


class FacetsResponse(ContextResponse):
    request_id: str
    collection_id: UUID
    collection_name: str
    field: str
    facets: list[FacetValue]


class ContextSourceIdentity(ContextResponse):
    schema_name: str = Field(alias="schema")
    table: str
    id: str

    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)


class ContextLane(ContextResponse):
    rank: int = Field(ge=1)
    score: float
    metric: ContextMetric

    @field_validator("score")
    @classmethod
    def _finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class Relationship(ContextResponse):
    type: str
    direction: ContextGraphDirection | str
    from_: ContextSourceIdentity = Field(alias="from")
    to: ContextSourceIdentity

    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)


class GraphLane(ContextResponse):
    rank: int | None
    depth: int | None
    relationships: list[Relationship]


class FusionMetadata(ContextResponse):
    method: Literal["weighted_rrf"]
    k: Literal[60]
    context_weight: float
    graph_weight: float


class LexicalLane(ContextResponse):
    rank: int = Field(ge=1)
    score: float

    @field_validator("score")
    @classmethod
    def _finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class JointGraphLane(ContextResponse):
    rank: int = Field(ge=1)
    depth: int = Field(ge=1, le=MAX_GRAPH_DEPTH)
    relationships: list[Relationship]


class JointScoreBreakdown(ContextResponse):
    semantic: float
    lexical: float
    graph: float
    total: float

    @field_validator("semantic", "lexical", "graph", "total")
    @classmethod
    def _finite_contribution(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("contribution must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def _total_matches_lanes(self) -> JointScoreBreakdown:
        if not math.isclose(
            self.total,
            self.semantic + self.lexical + self.graph,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise ValueError("total must equal the sum of lane contributions")
        return self


class JointFusionWeights(ContextResponse):
    semantic: float = Field(ge=0, le=1)
    lexical: float = Field(ge=0, le=1)
    graph: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _normalized(self) -> JointFusionWeights:
        values = (self.semantic, self.lexical, self.graph)
        if not all(math.isfinite(value) for value in values) or not math.isclose(
            sum(values), 1.0, rel_tol=1e-9, abs_tol=1e-9
        ):
            raise ValueError("fusion weights must be normalized")
        return self


class JointFusionMetadata(ContextResponse):
    method: Literal["joint_weighted_rrf"]
    k: Literal[60]
    weights: JointFusionWeights


class JointTrace(ContextResponse):
    semantic_candidates: int = Field(ge=0, le=MAX_RANKED_LIMIT)
    lexical_candidates: int = Field(ge=0, le=MAX_RANKED_LIMIT)
    explicit_seeds: int = Field(ge=0, le=MAX_JOINT_SEEDS)
    retrieval_seeds: int = Field(ge=0, le=MAX_JOINT_SEEDS)
    retained_seeds: int = Field(ge=0, le=MAX_JOINT_SEEDS)
    graph_candidates: int = Field(ge=0, le=MAX_RANKED_LIMIT)
    combined_candidates: int = Field(ge=0, le=MAX_RANKED_LIMIT * 3)
    rescored_candidates: int = Field(ge=0, le=MAX_RANKED_LIMIT * 3)


class ContextSearchResult(ContextResponse):
    point_id: int
    source: ContextSourceIdentity
    rank: int
    score: float
    score_kind: ContextScoreKind | str
    metric: ContextMetric | None = None
    properties: dict[str, Any]
    group_value: str | None = None
    group_rank: int | None = None

    @field_validator("score")
    @classmethod
    def _finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class ContextTextHybridResult(ContextSearchResult):
    score_kind: Literal[ContextScoreKind.RRF]
    rrf_k: Literal[60]


class ContextGraphHybridResult(ContextSearchResult):
    mode: Literal[
        ContextRankedMode.GRAPH_FIRST,
        ContextRankedMode.VECTOR_FIRST,
        ContextRankedMode.RANK_FUSION,
    ]
    context: ContextLane | None
    graph: GraphLane | None
    fusion: FusionMetadata | None


class ContextJointResult(ContextSearchResult):
    score_kind: Literal[ContextScoreKind.JOINT_WEIGHTED_RRF]
    metric: Literal[None] = None
    introduced_by_graph: bool
    baseline_rank: int | None = Field(ge=1)
    rank_lift: int | None
    context: ContextLane
    lexical: LexicalLane | None
    graph: JointGraphLane | None
    score_breakdown: JointScoreBreakdown

    @model_validator(mode="after")
    def _graph_introduction(self) -> ContextJointResult:
        if self.introduced_by_graph and (
            self.baseline_rank is not None or self.rank_lift is not None
        ):
            raise ValueError("graph-introduced results require null baseline fields")
        if self.introduced_by_graph and self.graph is None:
            raise ValueError("graph-introduced results require graph evidence")
        if not self.introduced_by_graph and (
            self.baseline_rank is None or self.rank_lift is None
        ):
            raise ValueError("non-graph-introduced results require baseline fields")
        if not math.isclose(
            self.score,
            self.score_breakdown.total,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise ValueError("score must equal the contribution total")
        return self


class ContextWarning(ContextResponse):
    code: str
    message: str
    details: dict[str, int | float | str]


class RankedCollection(ContextResponse):
    id: UUID
    name: str


class RankedResponse(ContextResponse):
    request_id: str
    collection: RankedCollection
    mode: ContextRankedMode | str
    results: list[ContextSearchResult | ContextTextHybridResult | ContextGraphHybridResult]
    warnings: list[ContextWarning]


class ContextJointResponse(ContextResponse):
    request_id: str
    collection: RankedCollection
    mode: Literal[ContextRankedMode.JOINT]
    results: list[ContextJointResult]
    fusion: JointFusionMetadata
    trace: JointTrace
    warnings: list[ContextWarning]


class RecallCheckResponse(ContextResponse):
    request_id: str
    collection_id: UUID
    collection_name: str
    exact_count: int
    candidate_count: int
    intersection_count: int
    recall: float
    minimum_recall: float
    status: ContextRecallStatus | str


REQUEST_MODEL_TYPES = (
    EmptyRequest,
    DiscoveryRequest,
    ContextSourceRequest,
    ContextVectorRequest,
    JsonbFilterPathRequest,
    CollectionCreateRequest,
    CollectionSetDefaultRequest,
    CollectionUpdateRequest,
    CollectionDeleteRequest,
    FilterColumnRequest,
    FilterJsonbPathRequest,
    PointKeysRequest,
    CountRequest,
    FacetsRequest,
    DenseSearchRequest,
    GroupedSearchRequest,
    RecallCheckRequest,
    TextHybridSearchRequest,
    GraphStart,
    GraphFirstSearchRequest,
    VectorFirstSearchRequest,
    RankFusionWeights,
    RankFusionSearchRequest,
    JointWeights,
    JointSearchRequest,
)

RESPONSE_MODEL_TYPES = (
    ErrorEnvelope,
    CapabilitiesResponse,
    DiscoveryResponse,
    PreflightResponse,
    ContextCollection,
    CollectionListResponse,
    CollectionGetResponse,
    CollectionStatusResponse,
    VerificationResponse,
    DiagnosticsResponse,
    FilterListResponse,
    PointStatusResponse,
    PointScrollResponse,
    PointMutationResponse,
    ContextOperation,
    OperationEnvelope,
    OperationListResponse,
    CountResponse,
    FacetsResponse,
    RankedResponse,
    LexicalLane,
    JointGraphLane,
    JointScoreBreakdown,
    JointFusionWeights,
    JointFusionMetadata,
    JointTrace,
    ContextJointResult,
    ContextJointResponse,
    RecallCheckResponse,
)

NESTED_RESPONSE_MODEL_TYPES = (
    RuntimeCapabilities,
    DiscoveryReason,
    DiscoverySource,
    DiscoveryVector,
    DiscoveryCandidate,
    PreflightCheck,
    PreflightBlocker,
    PreflightOwnership,
    DeletionPlan,
    ContextOperationFailure,
    VerificationCheck,
    DiagnosticCheck,
    RecommendedAction,
    FilterRegistration,
    PointMapping,
    FacetValue,
    ContextSourceIdentity,
    ContextLane,
    Relationship,
    GraphLane,
    FusionMetadata,
    ContextSearchResult,
    ContextTextHybridResult,
    ContextGraphHybridResult,
    ContextWarning,
    RankedCollection,
)

PUBLIC_MODEL_TYPES = REQUEST_MODEL_TYPES + RESPONSE_MODEL_TYPES + NESTED_RESPONSE_MODEL_TYPES


__all__ = [model.__name__ for model in PUBLIC_MODEL_TYPES] + [
    "ContextRequest",
    "ContextResponse",
    "NESTED_RESPONSE_MODEL_TYPES",
    "PUBLIC_MODEL_TYPES",
    "REQUEST_MODEL_TYPES",
    "RESPONSE_MODEL_TYPES",
]
