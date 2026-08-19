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
    ContextOnboardingStatus,
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
    name: str | None = None
    column_name: str = "embedding"
    dimensions: int = Field(ge=1, le=16_000)
    metric: ContextMetric = ContextMetric.COSINE

    @field_validator("name", "column_name")
    @classmethod
    def _column(cls, value: str | None, info) -> str | None:
        if value is not None:
            require_valid(validate_identifier(value, field=info.field_name))
        return value


class ContextVectorCreateRequest(ContextVectorRequest):
    mode: Literal["existing", "add_column"] = "existing"
    index_kind: ContextIndexKind = ContextIndexKind.HNSW
    set_default: bool = False


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
    default_vector_name: str | None = None

    @field_validator("text_column")
    @classmethod
    def _text_column(cls, value: str | None) -> str | None:
        if value is not None:
            require_valid(validate_identifier(value, field="text_column"))
        return value

    @field_validator("default_vector_name")
    @classmethod
    def _default_vector_name(cls, value: str | None) -> str | None:
        if value is not None:
            require_valid(validate_identifier(value, field="default_vector_name"))
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


class CollectionAliasRequest(ContextRequest):
    alias_name: str
    target_collection_name: str

    @field_validator("alias_name", "target_collection_name")
    @classmethod
    def _alias_name(cls, value: str, info) -> str:
        require_valid(validate_identifier(value, field=info.field_name))
        return value


class CollectionLimitsRequest(ContextRequest):
    strict_mode: bool
    max_dimensions: int | None = Field(default=None, ge=1, le=16_000)
    max_vectors: int | None = Field(default=None, ge=1)
    max_points: int | None = Field(default=None, ge=1)
    max_filter_nodes: int | None = Field(default=None, ge=1)
    max_search_limit: int | None = Field(default=None, ge=1)
    max_candidate_budget: int | None = Field(default=None, ge=1)
    query_timeout_ms: int | None = Field(default=None, ge=1)
    max_index_memory_bytes: int | None = Field(default=None, ge=1)


class VectorConfigureRequest(ContextRequest):
    hnsw_options: dict[str, Any]
    quantization_options: dict[str, Any]
    status: Literal["ready", "building", "disabled", "failed"]


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


class BulkPointKeysRequest(PointKeysRequest):
    collection: str
    batch_size: int = Field(default=1000, ge=1)


class BackfillPointsRequest(ContextRequest):
    collection: str
    batch_size: int = Field(default=1000, ge=1)


class SetPayloadRequest(PointKeysRequest):
    collection: str
    payload: dict[str, Any] = Field(min_length=1)


class DeletePayloadRequest(PointKeysRequest):
    collection: str
    payload_keys: list[str] = Field(min_length=1)

    @field_validator("payload_keys")
    @classmethod
    def _payload_keys(cls, value: list[str]) -> list[str]:
        for key in value:
            require_valid(validate_identifier(key, field="payload_key"))
        return value


class ClearPayloadRequest(PointKeysRequest):
    collection: str


class RecommendRequest(ContextRequest):
    collection: str
    positive_point_ids: list[int] | None = None
    negative_point_ids: list[int] = Field(default_factory=list)
    positive_vectors: list[list[float]] | None = None
    negative_vectors: list[list[float]] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=MAX_RANKED_LIMIT)

    @model_validator(mode="after")
    def _examples(self) -> RecommendRequest:
        point_form = self.positive_point_ids is not None
        vector_form = self.positive_vectors is not None
        if point_form == vector_form:
            raise ValueError("provide exactly one positive example form")
        if point_form:
            ids = (self.positive_point_ids or []) + self.negative_point_ids
            if not self.positive_point_ids or any(point_id <= 0 for point_id in ids):
                raise ValueError("recommendation point ids must be positive")
            if self.negative_vectors:
                raise ValueError("point and vector examples cannot be mixed")
        else:
            if self.negative_point_ids:
                raise ValueError("point and vector examples cannot be mixed")
            for vector in (self.positive_vectors or []) + self.negative_vectors:
                require_valid(validate_embedding(vector))
            if not self.positive_vectors:
                raise ValueError("positive_vectors must not be empty")
        return self


class ContextPointDiscoveryRequest(ContextRequest):
    collection: str
    context_point_ids: list[int] = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=MAX_RANKED_LIMIT)

    @field_validator("context_point_ids")
    @classmethod
    def _context_ids(cls, value: list[int]) -> list[int]:
        if any(point_id <= 0 for point_id in value):
            raise ValueError("context point ids must be positive")
        return value


class RegisterModelVersionRequest(ContextRequest):
    collection: str
    model_name: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    dimensions: int = Field(ge=1, le=16_000)
    metric: Literal["l2", "inner_product", "cosine", "l1"]


class CreateEmbeddingMigrationRequest(ContextRequest):
    collection: str
    source_model_name: str = Field(min_length=1, max_length=128)
    source_model_version: str = Field(min_length=1, max_length=128)
    target_model_name: str = Field(min_length=1, max_length=128)
    target_model_version: str = Field(min_length=1, max_length=128)
    total_points: int = Field(ge=0)


class UpdateEmbeddingMigrationRequest(ContextRequest):
    processed_points: int = Field(ge=0)
    status: Literal["planned", "running", "completed", "failed"]


class RawVectorSearchRequest(ContextRequest):
    query: list[float]
    point_ids: list[int] = Field(min_length=1)
    vectors: list[list[float]] = Field(min_length=1)
    metric: Literal["l2", "inner_product", "cosine", "l1"]
    limit: int = Field(default=10, ge=1, le=MAX_RANKED_LIMIT)

    @model_validator(mode="after")
    def _vectors_match(self) -> RawVectorSearchRequest:
        require_valid(validate_embedding(self.query))
        if len(self.point_ids) != len(self.vectors):
            raise ValueError("point_ids and vectors must have the same length")
        if any(point_id < 0 for point_id in self.point_ids):
            raise ValueError("point ids must not be negative")
        for vector in self.vectors:
            require_valid(validate_embedding(vector))
            if len(vector) != len(self.query):
                raise ValueError("candidate vector dimensions must match query")
        return self


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
    vector_name: str | None = None
    embedding: list[float]
    limit: int = Field(default=10, ge=1, le=MAX_RANKED_LIMIT)

    @field_validator("embedding", mode="before")
    @classmethod
    def _embedding(cls, value: list[float]) -> list[float]:
        require_valid(validate_embedding(value))
        return value

    @field_validator("vector_name")
    @classmethod
    def _vector_name(cls, value: str | None) -> str | None:
        if value is not None:
            require_valid(validate_identifier(value, field="vector_name"))
        return value


class CandidateSearchRequest(DenseSearchRequest):
    candidate_point_ids: list[int] = Field(min_length=1)

    @field_validator("candidate_point_ids")
    @classmethod
    def _candidate_ids(cls, value: list[int]) -> list[int]:
        if any(point_id <= 0 for point_id in value):
            raise ValueError("candidate point ids must be positive")
        return value


class GroupedSearchRequest(ContextRequest):
    collection: str
    vector_name: str | None = None
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

    @field_validator("vector_name")
    @classmethod
    def _vector_name(cls, value: str | None) -> str | None:
        if value is not None:
            require_valid(validate_identifier(value, field="vector_name"))
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
    vector_name: str | None = None
    embedding: list[float]
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=MAX_RANKED_LIMIT)

    @field_validator("embedding", mode="before")
    @classmethod
    def _embedding(cls, value: list[float]) -> list[float]:
        require_valid(validate_embedding(value))
        return value

    @field_validator("vector_name")
    @classmethod
    def _vector_name(cls, value: str | None) -> str | None:
        if value is not None:
            require_valid(validate_identifier(value, field="vector_name"))
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


class ContextQueryPlan(ContextRequest):
    """Immutable JSON query plan compatible with pgContext 0.2.0 builders."""

    kind: Literal[
        "nearest",
        "sparse_nearest",
        "full_text",
        "late_interaction",
        "recommend",
        "discover",
        "lookup",
        "prefetch",
        "weight",
        "score_threshold",
        "formula",
        "rerank",
    ]
    vector: list[float] | str | None = None
    vector_name: str | None = None
    filter: dict[str, Any] | None = None
    text_query: str | None = None
    text_column: str | None = None
    query_vectors: list[list[float]] | None = None
    candidates_per_query: int | None = Field(default=None, ge=1)
    positive_point_ids: list[int] | None = None
    negative_point_ids: list[int] | None = None
    context_point_ids: list[int] | None = None
    point_ids: list[int] | None = None
    branches: list[ContextQueryPlan] | None = None
    branch: ContextQueryPlan | None = None
    weight: float | None = None
    min_score: float | None = None
    max_score: float | None = None
    formula: str | None = None
    limit: int | None = Field(default=None, ge=1)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @field_validator("vector_name", "text_column")
    @classmethod
    def _query_identifier(cls, value: str | None, info) -> str | None:
        if value is not None:
            require_valid(validate_identifier(value, field=info.field_name))
        return value

    @field_validator("text_query", "formula")
    @classmethod
    def _query_text(cls, value: str | None, info) -> str | None:
        if value is not None and not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("positive_point_ids", "negative_point_ids", "context_point_ids", "point_ids")
    @classmethod
    def _query_point_ids(cls, value: list[int] | None, info) -> list[int] | None:
        if value is not None and any(point_id <= 0 for point_id in value):
            raise ValueError(f"{info.field_name} must contain only positive point ids")
        return value

    @model_validator(mode="after")
    def _query_shape(self) -> ContextQueryPlan:
        required = {
            "nearest": {"vector", "limit"},
            "sparse_nearest": {"vector_name", "vector", "limit"},
            "full_text": {"text_query", "text_column", "limit"},
            "late_interaction": {"query_vectors", "candidates_per_query", "limit"},
            "recommend": {"positive_point_ids", "negative_point_ids", "limit"},
            "discover": {"context_point_ids", "limit"},
            "lookup": {"point_ids"},
            "prefetch": {"branches"},
            "weight": {"branch", "weight"},
            "score_threshold": {"branch"},
            "formula": {"branch", "formula"},
            "rerank": {"branch", "limit"},
        }[self.kind]
        allowed = required | {
            "nearest": {"vector_name", "filter"},
            "sparse_nearest": {"filter"},
            "score_threshold": {"min_score", "max_score"},
        }.get(self.kind, set())
        supplied = self.model_fields_set - {"kind"}
        missing = required - supplied
        unexpected = supplied - allowed
        if missing:
            raise ValueError(f"{self.kind} query plan is missing {sorted(missing)}")
        if unexpected:
            raise ValueError(f"{self.kind} query plan does not accept {sorted(unexpected)}")
        if self.kind == "nearest":
            if not isinstance(self.vector, list):
                raise ValueError("nearest vector must be a dense vector")
            require_valid(validate_embedding(self.vector))
        elif self.kind == "sparse_nearest":
            if not isinstance(self.vector, str) or not self.vector.strip():
                raise ValueError("sparse_nearest vector must be a sparse vector string")
        if self.query_vectors is not None:
            if not self.query_vectors:
                raise ValueError("query_vectors must not be empty")
            dimensions = len(self.query_vectors[0])
            for vector in self.query_vectors:
                require_valid(validate_embedding(vector, expected_dimensions=dimensions))
        if self.kind == "recommend" and not self.positive_point_ids:
            raise ValueError("recommend requires at least one positive point id")
        if self.kind == "discover" and not self.context_point_ids:
            raise ValueError("discover requires at least one context point id")
        if self.kind == "lookup" and not self.point_ids:
            raise ValueError("lookup requires at least one point id")
        if self.kind == "prefetch" and not self.branches:
            raise ValueError("prefetch requires at least one branch")
        if self.weight is not None and (not math.isfinite(self.weight) or self.weight < 0):
            raise ValueError("weight must be finite and non-negative")
        for value in (self.min_score, self.max_score):
            if value is not None and not math.isfinite(value):
                raise ValueError("score thresholds must be finite")
        if (
            self.min_score is not None
            and self.max_score is not None
            and self.min_score > self.max_score
        ):
            raise ValueError("min_score must not exceed max_score")
        return self


class QueryExecuteRequest(ContextRequest):
    collection: str
    plan: ContextQueryPlan

    @field_validator("collection")
    @classmethod
    def _query_collection(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("collection must not be blank")
        return value


class QueryExplainRequest(ContextRequest):
    collection: str
    text_column: str

    @field_validator("collection")
    @classmethod
    def _explain_collection(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("collection must not be blank")
        return value

    @field_validator("text_column")
    @classmethod
    def _explain_column(cls, value: str) -> str:
        require_valid(validate_identifier(value, field="text_column"))
        return value


class ErrorBody(ContextResponse):
    code: str
    variant: str | None = None
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
    pgvector_version: str | None = None
    pgvector_schema: str | None = None
    pgcontext_pgvector_version: str | None = None
    same_column_bridge: bool = False


class PgContextCompatibilityCapabilities(ContextResponse):
    target_version: Literal["0.2.0"]
    stable_items: int
    aligned: int
    managed_equivalent: int
    partial: int
    sql_only: int
    deferred: int
    missing_sdk: Literal[0]


class CapabilitiesResponse(ContextResponse):
    request_id: str
    contract_version: Literal["context.v1"]
    product_status: Literal["preview"]
    pgcontext_compatibility: PgContextCompatibilityCapabilities
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


class DiscoveryColumn(ContextResponse):
    column_name: str
    data_type: str
    nullable: bool
    ordinal_position: int


class DiscoveryCandidate(ContextResponse):
    classification: ContextSourceClassification | str
    source: DiscoverySource
    vectors: list[DiscoveryVector]
    columns: list[DiscoveryColumn] = Field(default_factory=list)
    reasons: list[DiscoveryReason]


class DiscoveryResponse(ContextResponse):
    request_id: str
    candidates: list[DiscoveryCandidate]


class ContextOnboardingCandidate(ContextResponse):
    vector_configuration_id: UUID
    name: str
    schema_name: str
    table_name: str
    row_id_column: str
    embedding_column: str
    dimensions: int
    metric: ContextMetric
    is_default: bool


class ContextOnboardingResponse(ContextResponse):
    request_id: str
    status: ContextOnboardingStatus | str
    compatibility_generation: int
    candidates: list[ContextOnboardingCandidate]
    offer_acknowledged: bool
    selected_vector_configuration_id: UUID | None
    completed_collection_id: UUID | None
    evaluated_at: datetime | None
    updated_at: datetime | None


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


class ContextCollectionVector(ContextResponse):
    id: UUID
    name: str
    column_name: str
    is_default: bool
    owns_vector_column: bool
    vector_type_owner: Literal["pgcontext", "pgvector"] = "pgcontext"
    dimensions: int
    metric: ContextMetric
    index_kind: ContextIndexKind
    index_name: str | None
    owns_index: bool
    index_status: ContextIndexStatus | str
    last_error_code: str | None
    last_error_stage: str | None
    created_at: datetime
    updated_at: datetime


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
    default_vector_name: str
    vectors: list[ContextCollectionVector]
    max_search_limit: int
    text_column: str | None
    result_columns: list[str]
    filter_columns: list[str]
    jsonb_filter_paths: list[dict[str, Any]]
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
    drop_owned_indexes: list[str]
    preserve_source_table: str
    preserve_source_columns: list[str]
    preserve_indexes: list[str]


class CollectionGetResponse(ContextResponse):
    request_id: str
    collection: ContextCollection
    deletion_plan: DeletionPlan


class CollectionAlias(ContextResponse):
    alias_name: str
    collection_name: str


class CollectionAliasResponse(ContextResponse):
    request_id: str
    alias: CollectionAlias


class CollectionAliasListResponse(ContextResponse):
    request_id: str
    aliases: list[CollectionAlias]


class CollectionAliasDropResponse(ContextResponse):
    request_id: str
    alias_name: str
    dropped: bool


class PgContextCollectionInfo(ContextResponse):
    collection_id: int = Field(gt=0)
    collection_name: str
    owner_name: str
    table_schema: str | None
    table_name: str | None


class PgContextCollectionInfoResponse(ContextResponse):
    request_id: str
    collection: PgContextCollectionInfo


class CollectionLimits(ContextResponse):
    strict_mode: bool
    max_dimensions: int | None
    max_vectors: int | None
    max_points: int | None
    max_filter_nodes: int | None
    max_search_limit: int | None
    max_candidate_budget: int | None
    query_timeout_ms: int | None
    max_index_memory_bytes: int | None


class CollectionLimitsResponse(ContextResponse):
    request_id: str
    collection_name: str
    limits: CollectionLimits


class PgContextVectorMetadata(ContextResponse):
    collection_name: str
    vector_name: str
    table_schema: str
    table_name: str
    vector_column: str
    dimensions: int = Field(ge=1, le=16_000)
    metric: str
    hnsw_options: dict[str, Any]
    quantization_options: dict[str, Any]
    status: str


class CollectionVectorsResponse(ContextResponse):
    request_id: str
    collection_name: str
    vectors: list[PgContextVectorMetadata]


class VectorConfigureResponse(ContextResponse):
    request_id: str
    vector: PgContextVectorMetadata


class ContextOperationFailure(ContextResponse):
    code: str
    variant: str | None = None
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
    vectors: list[ContextCollectionVector]
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


class PointBatchProgress(ContextResponse):
    batch_number: int
    processed_count: int
    inserted_count: int | None = None
    reactivated_count: int | None = None
    deleted_count: int | None = None
    missing_count: int | None = None


class PointBatchResponse(ContextResponse):
    request_id: str
    batches: list[PointBatchProgress]


class PayloadMutationResult(ContextResponse):
    source_key: str
    updated: bool


class PayloadMutationResponse(ContextResponse):
    request_id: str
    results: list[PayloadMutationResult]


class PgContextScoredPoint(ContextResponse):
    point_id: int
    source_key: str
    score: float


class PgContextScoredResponse(ContextResponse):
    request_id: str
    results: list[PgContextScoredPoint]


class IndexStatusRow(ContextResponse):
    index_schema: str
    index_name: str
    table_schema: str
    table_name: str
    access_method: str
    is_valid: bool
    is_ready: bool
    is_live: bool
    status: str


class IndexDiagnosticsRow(ContextResponse):
    index_schema: str
    index_name: str
    table_schema: str
    table_name: str
    access_method: str
    status: str
    context_error: str | None
    sqlstate: str | None
    repair_advice: str


class IndexMemoryEstimateRow(ContextResponse):
    index_schema: str
    index_name: str
    table_schema: str
    table_name: str
    access_method: str
    estimated_rows: int
    dimensions: int
    vector_bytes: int
    link_bytes: int
    total_bytes: int
    status: str


class IndexAdvisorRow(ContextResponse):
    collection_name: str
    filter_key: str | None
    column_name: str | None
    recommendation: str
    detail: str
    suggested_sql: str | None


class OptimizationStatusRow(ContextResponse):
    collection_name: str
    table_schema: str | None
    table_name: str | None
    has_source_table: bool
    source_table_exists: bool
    registered_vectors: int
    active_points: int
    filter_fields: int
    hnsw_indexes: int
    status: str


class VacuumAdviceRow(ContextResponse):
    index_schema: str
    index_name: str
    table_schema: str
    table_name: str
    access_method: str
    estimated_index_tuples: int
    index_pages: int
    dead_table_tuples: int
    status: str


class TelemetryRow(ContextResponse):
    collection_name: str
    table_schema: str | None
    table_name: str | None
    has_source_table: bool
    source_table_exists: bool
    registered_vectors: int
    active_points: int
    deleted_points: int
    filter_fields: int
    hnsw_indexes: int
    status: str


class ModelVersionRow(ContextResponse):
    collection_name: str
    model_name: str
    model_version: str
    dimensions: int
    metric: str
    is_active: bool


class EmbeddingMigrationRow(ContextResponse):
    migration_id: int
    collection_name: str
    source_model: str
    source_version: str
    target_model: str
    target_version: str
    status: str
    total_points: int
    processed_points: int


class RawVectorSearchResult(ContextResponse):
    point_id: int
    score: float


class RawVectorSearchResponse(ContextResponse):
    request_id: str
    results: list[RawVectorSearchResult]


class QueryCohortStatsRow(ContextResponse):
    collection_name: str
    cohort: str
    query_kind: str
    query_count: int
    total_results: int
    total_candidates: int | None
    total_rows_rechecked: int
    total_rows_pruned: int
    avg_recall_threshold: float | None
    avg_recall_achieved: float | None
    latency_bucket: str
    lifecycle_state: str
    avg_latency_ms: float
    status: str


class QueryExecutionStatsRow(ContextResponse):
    collection_name: str
    query_kind: str
    strategy: str
    query_count: int
    total_visits: int
    total_filter_candidates: int
    total_candidates: int
    total_rechecks: int
    total_stages: int
    total_expansions: int
    completion: str
    latency_bucket: str
    lifecycle_state: str
    avg_latency_ms: float


class QueryCohortStatsResponse(ContextResponse):
    request_id: str
    rows: list[QueryCohortStatsRow]


class QueryExecutionStatsResponse(ContextResponse):
    request_id: str
    rows: list[QueryExecutionStatsRow]


class IndexStatusResponse(ContextResponse):
    request_id: str
    rows: list[IndexStatusRow]


class IndexDiagnosticsResponse(ContextResponse):
    request_id: str
    rows: list[IndexDiagnosticsRow]


class IndexMemoryEstimateResponse(ContextResponse):
    request_id: str
    rows: list[IndexMemoryEstimateRow]


class IndexAdvisorResponse(ContextResponse):
    request_id: str
    rows: list[IndexAdvisorRow]


class OptimizationStatusResponse(ContextResponse):
    request_id: str
    rows: list[OptimizationStatusRow]


class VacuumAdviceResponse(ContextResponse):
    request_id: str
    rows: list[VacuumAdviceRow]


class TelemetryResponse(ContextResponse):
    request_id: str
    rows: list[TelemetryRow]


class ModelVersionsResponse(ContextResponse):
    request_id: str
    rows: list[ModelVersionRow]


class EmbeddingMigrationsResponse(ContextResponse):
    request_id: str
    rows: list[EmbeddingMigrationRow]


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
        if not self.introduced_by_graph and (self.baseline_rank is None or self.rank_lift is None):
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


class QueryExecutionResult(ContextResponse):
    point_id: int = Field(gt=0)
    source_key: str
    score: float

    @field_validator("score")
    @classmethod
    def _query_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class QueryExecutionResponse(ContextResponse):
    request_id: str
    collection: RankedCollection
    results: list[QueryExecutionResult]


class QueryExplainRow(ContextResponse):
    stage: str
    detail: str
    branch: str | None
    strategy: str
    status: str
    estimated_candidates: int | None
    candidate_budget: int | None


class QueryExplainResponse(ContextResponse):
    request_id: str
    collection: RankedCollection
    rows: list[QueryExplainRow]


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
    ContextVectorCreateRequest,
    JsonbFilterPathRequest,
    CollectionCreateRequest,
    CollectionSetDefaultRequest,
    CollectionUpdateRequest,
    CollectionDeleteRequest,
    CollectionAliasRequest,
    CollectionLimitsRequest,
    VectorConfigureRequest,
    FilterColumnRequest,
    FilterJsonbPathRequest,
    PointKeysRequest,
    BulkPointKeysRequest,
    BackfillPointsRequest,
    SetPayloadRequest,
    DeletePayloadRequest,
    ClearPayloadRequest,
    CountRequest,
    FacetsRequest,
    DenseSearchRequest,
    CandidateSearchRequest,
    RecommendRequest,
    ContextPointDiscoveryRequest,
    RegisterModelVersionRequest,
    CreateEmbeddingMigrationRequest,
    UpdateEmbeddingMigrationRequest,
    RawVectorSearchRequest,
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
    ContextQueryPlan,
    QueryExecuteRequest,
    QueryExplainRequest,
)

RESPONSE_MODEL_TYPES = (
    ErrorEnvelope,
    CapabilitiesResponse,
    DiscoveryResponse,
    ContextOnboardingResponse,
    PreflightResponse,
    ContextCollection,
    CollectionListResponse,
    CollectionGetResponse,
    CollectionAliasResponse,
    CollectionAliasListResponse,
    CollectionAliasDropResponse,
    PgContextCollectionInfoResponse,
    CollectionLimitsResponse,
    CollectionVectorsResponse,
    VectorConfigureResponse,
    CollectionStatusResponse,
    VerificationResponse,
    DiagnosticsResponse,
    FilterListResponse,
    PointStatusResponse,
    PointScrollResponse,
    PointMutationResponse,
    PointBatchResponse,
    PayloadMutationResponse,
    PgContextScoredResponse,
    IndexStatusResponse,
    IndexDiagnosticsResponse,
    IndexMemoryEstimateResponse,
    IndexAdvisorResponse,
    OptimizationStatusResponse,
    VacuumAdviceResponse,
    TelemetryResponse,
    ModelVersionsResponse,
    EmbeddingMigrationsResponse,
    RawVectorSearchResponse,
    QueryCohortStatsResponse,
    QueryExecutionStatsResponse,
    ContextOperation,
    OperationEnvelope,
    OperationListResponse,
    CountResponse,
    FacetsResponse,
    RankedResponse,
    QueryExecutionResponse,
    QueryExplainResponse,
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
    PgContextCompatibilityCapabilities,
    DiscoveryReason,
    DiscoverySource,
    DiscoveryVector,
    DiscoveryColumn,
    DiscoveryCandidate,
    ContextOnboardingCandidate,
    PreflightCheck,
    PreflightBlocker,
    PreflightOwnership,
    ContextCollectionVector,
    DeletionPlan,
    CollectionAlias,
    PgContextCollectionInfo,
    CollectionLimits,
    PgContextVectorMetadata,
    ContextOperationFailure,
    VerificationCheck,
    DiagnosticCheck,
    RecommendedAction,
    FilterRegistration,
    PointMapping,
    PointBatchProgress,
    PayloadMutationResult,
    PgContextScoredPoint,
    IndexStatusRow,
    IndexDiagnosticsRow,
    IndexMemoryEstimateRow,
    IndexAdvisorRow,
    OptimizationStatusRow,
    VacuumAdviceRow,
    TelemetryRow,
    ModelVersionRow,
    EmbeddingMigrationRow,
    RawVectorSearchResult,
    QueryCohortStatsRow,
    QueryExecutionStatsRow,
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
    QueryExecutionResult,
    QueryExplainRow,
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
