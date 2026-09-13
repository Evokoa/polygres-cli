"""Shared contracts for managed source and query embeddings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=63)]


class UsageKind(str, Enum):
    GENERATION = "generation"
    QUERY = "query"


class ProcessingMode(str, Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class EmbeddingStatus(str, Enum):
    INITIALIZING = "initializing"
    PROCESSING = "processing"
    CURRENT = "current"
    PENDING = "pending"
    PAUSED = "paused"
    QUOTA_EXHAUSTED = "quota_exhausted"
    NEEDS_ATTENTION = "needs_attention"
    REMOVED = "removed"


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Chunking(RequestModel):
    enabled: bool = False
    size_tokens: int = Field(default=512, ge=32, le=8192)
    overlap_tokens: int = Field(default=64, ge=0, le=2048)

    @model_validator(mode="after")
    def valid_overlap(self) -> Chunking:
        if self.overlap_tokens >= self.size_tokens:
            raise ValueError("overlap_tokens must be smaller than size_tokens")
        return self


class ModelPublic(ResponseModel):
    id: UUID
    name: str
    provider: Literal["openai", "qwen"]
    model: str
    revision: str
    dimensions: list[int]
    default_dimensions: int
    max_input_tokens: int
    enabled: bool
    price_version: str
    # Exact decimal accounting: millionths of one organization credit per token.
    microcredits_per_token: Decimal
    source_settings: dict[str, Any] = Field(default_factory=dict)
    query_settings: dict[str, Any] = Field(default_factory=dict)


class ModelCreate(RequestModel):
    name: str = Field(min_length=1, max_length=100)
    provider: Literal["openai", "qwen"]
    model: str = Field(min_length=1, max_length=160)
    revision: str = Field(min_length=1, max_length=120)
    dimensions: list[int] = Field(min_length=1, max_length=64)
    default_dimensions: int = Field(ge=1, le=4096)
    max_input_tokens: int = Field(ge=32, le=32768)
    max_batch_inputs: int = Field(default=64, ge=1, le=2048)
    max_batch_tokens: int = Field(default=16384, ge=32, le=300000)
    endpoint: str = Field(min_length=1, max_length=2048)
    # Compatibility name: selects an approved gateway connection, never a caller environment.
    credential_env: str = Field(pattern=r"^POLYGRES_EMBEDDING_[A-Z0-9_]+$")
    tokenizer: str = Field(min_length=1, max_length=300)
    tokenizer_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_settings: dict[str, Any] = Field(default_factory=dict)
    query_settings: dict[str, Any] = Field(default_factory=dict)
    price_version: str = Field(min_length=1, max_length=120)
    microcredits_per_token: Decimal = Field(ge=0, le=1000000000, max_digits=22, decimal_places=12)
    enabled: bool = False

    @field_validator("dimensions")
    @classmethod
    def valid_dimensions(cls, values: list[int]) -> list[int]:
        if any(value < 1 or value > 4096 for value in values) or len(set(values)) != len(values):
            raise ValueError("dimensions must contain distinct supported sizes between 1 and 4096")
        return sorted(values)

    @field_validator("source_settings", "query_settings")
    @classmethod
    def valid_provider_settings(cls, value: dict[str, Any]) -> dict[str, Any]:
        if set(value) - {"input_type", "task_type", "instruction", "prefix", "normalize"}:
            raise ValueError("unsupported source or query embedding setting")
        if any(
            not isinstance(v, bool) if k == "normalize" else not isinstance(v, str)
            for k, v in value.items()
        ):
            raise ValueError("normalize must be boolean; other settings must be strings")
        if any(isinstance(v, str) and len(v) > 2000 for v in value.values()):
            raise ValueError("embedding settings exceed maximum length")
        return value

    @model_validator(mode="after")
    def consistent_model(self) -> ModelCreate:
        from urllib.parse import urlsplit

        endpoint = urlsplit(self.endpoint)
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
        ):
            raise ValueError("provider endpoint must be an HTTPS URL without embedded credentials")
        if endpoint.query or endpoint.fragment:
            raise ValueError("provider endpoint cannot contain a query or fragment")
        if self.default_dimensions not in self.dimensions:
            raise ValueError("default_dimensions must be one of the supported dimensions")
        if self.max_batch_tokens < self.max_input_tokens:
            raise ValueError("max_batch_tokens must accommodate at least one maximum-sized input")
        if self.provider == "openai" and self.tokenizer != "cl100k_base":
            raise ValueError("OpenAI embeddings require the cl100k_base tokenizer")
        if self.provider == "qwen" and not self.tokenizer_sha256:
            raise ValueError("Qwen requires a pinned tokenizer artifact SHA-256")
        return self


class ModelPriceChange(RequestModel):
    price_version: str = Field(min_length=1, max_length=120)
    published_usd_per_million: Decimal = Field(ge=0, le=10000000, decimal_places=12)
    source_url: str = Field(pattern=r"^https://", max_length=2048)


class ModelStateChange(RequestModel):
    state: Literal["active", "retired", "disabled"]
    expected_version: int = Field(ge=1)
    pricing: ModelPriceChange | None = None


class ModelDeleteRequest(RequestModel):
    expected_version: int = Field(ge=1)


class ModelProbeRequest(RequestModel):
    attempt_id: UUID
    confirm_provider_charge: Literal[True]


# One organization credit has USD 0.01 face value; one microcredit is USD 0.00000001.
MICROCREDITS_PER_USD = 100_000_000


class QuotaPolicyRequest(RequestModel):
    version: str = Field(min_length=1, max_length=120)
    free_generation_microcredits: int = Field(ge=0, le=10**12)
    free_query_microcredits: int = Field(ge=0, le=10**12)
    paid_generation_microcredits: int = Field(ge=0, le=10**12)
    paid_query_microcredits: int = Field(ge=0, le=10**12)
    apply_immediately: bool = False

    @model_validator(mode="after")
    def paid_allowance(self) -> QuotaPolicyRequest:
        if (
            self.paid_generation_microcredits < self.free_generation_microcredits
            or self.paid_query_microcredits < self.free_query_microcredits
        ):
            raise ValueError("paid allowance cannot be smaller than the Free allowance")
        return self


class CreditSpendingRequest(RequestModel):
    enabled: bool
    cycle_credit_limit: int = Field(ge=0, le=1000000000)

    @model_validator(mode="after")
    def require_limit(self) -> CreditSpendingRequest:
        if self.enabled and self.cycle_credit_limit == 0:
            raise ValueError("a positive billing-cycle credit limit is required to enable spending")
        return self


class EmbeddingConfigurationCreate(RequestModel):
    name: str = Field(min_length=1, max_length=120)
    source_schema: Identifier
    source_table: Identifier
    source_key_columns: list[Identifier] = Field(min_length=1, max_length=16)
    source_text_column: Identifier
    existing_vector_column: Identifier | None = None
    confirm_original_model: bool = False
    model_id: UUID
    dimensions: int = Field(ge=1, le=4096)
    mode: ProcessingMode = ProcessingMode.AUTOMATIC
    use_credits: bool = False
    chunking: Chunking = Field(default_factory=Chunking)

    @model_validator(mode="after")
    def valid_copy(self) -> EmbeddingConfigurationCreate:
        if len(set(self.source_key_columns)) != len(self.source_key_columns):
            raise ValueError("source_key_columns must be distinct")
        if self.existing_vector_column and not self.confirm_original_model:
            raise ValueError("confirm the original model before copying existing vectors")
        if self.existing_vector_column and self.chunking.enabled:
            raise ValueError("whole-row vectors cannot seed chunk embeddings; choose generation")
        if self.source_schema.startswith("pg_") or self.source_schema.startswith("polygres_"):
            raise ValueError("platform-managed schemas cannot be watched embedding sources")
        return self


class EmbeddingConfigurationSettings(EmbeddingConfigurationCreate):
    """Persisted settings, including operator-managed processing limits."""

    batch_size: int = Field(default=100, ge=1, le=1000)


class EmbeddingConfigurationUpdate(RequestModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    mode: ProcessingMode | None = None
    use_credits: bool | None = None


class EmbeddingActionRequest(RequestModel):
    action: Literal["pause", "resume", "run", "retry", "reconcile"]


class EmbeddingRemoveRequest(RequestModel):
    delete_managed_output: bool
    expected_version: int = Field(ge=1)


class EmbeddingProgress(ResponseModel):
    embedded_rows: int | None = Field(
        default=None,
        description="Current source rows with completed embeddings, counted once per row.",
    )
    pending_rows: int | None = Field(
        default=None,
        description=(
            "Current source rows queued or processing, excluding deleted and empty-text rows."
        ),
    )
    copied: int = 0
    generated: int = 0
    pending: int = 0
    processing: int = 0
    recovering: int = Field(default=0, description="Pending jobs whose worker lease expired.")
    retrying: int = Field(default=0, description="Pending jobs delayed until their retry time.")
    next_retry_at: datetime | None = None
    failed: int = 0
    uncertain: int = 0
    deleted: int = 0
    input_tokens: int = 0
    context_pending: int = 0
    context_failed: int = 0


class EmbeddingConfiguration(ResponseModel):
    id: UUID
    project_id: str
    version: int
    settings: EmbeddingConfigurationSettings
    model: ModelPublic
    status: EmbeddingStatus
    managed_schema: str = "polygres_embeddings"
    managed_table: str
    progress: EmbeddingProgress = Field(default_factory=EmbeddingProgress)
    last_error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    initial_scan_complete: bool = False
    run_requested: bool = False


class UsageBucket(ResponseModel):
    kind: UsageKind
    included_microcredits: Decimal
    used_microcredits: Decimal
    reserved_microcredits: Decimal
    remaining_microcredits: Decimal


class ModelUsage(ResponseModel):
    model_id: UUID
    name: str
    price_version: str
    microcredits_per_token: Decimal
    input_tokens: int
    usage_microcredits: Decimal
    included_microcredits: Decimal
    additional_microcredits: Decimal


class EmbeddingUsage(ResponseModel):
    project_id: str
    period_start: datetime
    period_end: datetime
    period_kind: Literal["free", "paid"]
    policy_version: str
    generation: UsageBucket
    query: UsageBucket
    models: list[ModelUsage]
    credit_spending_enabled: bool
    cycle_credit_limit: int
    charged_microcredits: Decimal
    reserved_microcredits: Decimal
    available_credit_microcredits: Decimal | None = Field(default=None, ge=0)


class EmbeddingVectorColumn(ResponseModel):
    name: str
    dimensions: int | None = None


class EmbeddingSource(ResponseModel):
    schema_name: str
    table_name: str
    text_columns: list[str]
    key_options: list[list[str]]
    vector_columns: list[EmbeddingVectorColumn]


class EmbeddingPreview(ResponseModel):
    source_rows: int
    sampled_rows: int
    copyable_sample_rows: int
    missing_sample_rows: int
    sample_chunks: list[str]
    estimated_input_tokens: int
    estimated_storage_bytes: int
    estimated_microcredits: Decimal
    estimate_is_sampled: bool
    model: ModelPublic
    usage: EmbeddingUsage


class EmbeddingSearchRequest(RequestModel):
    configuration_id: UUID
    collection: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=131072)
    filter: dict[str, Any] | None = None
    limit: int = Field(default=10, ge=1, le=100)
    use_credits: bool = False


PUBLIC_MODEL_TYPES = tuple(
    value
    for value in tuple(globals().values())
    if isinstance(value, type)
    and issubclass(value, BaseModel)
    and value.__module__ == __name__
    and value not in {RequestModel, ResponseModel}
)
