"""Generated private Context subset. Do not edit by hand."""

from . import enums as _enums
from . import models as _models
from .enums import CONTEXT_OPERATION_STAGES
from .errors import CONTEXT_ERROR_CATALOG, ContextErrorCode, ContextErrorDescriptor
from .validation import (
    MAX_ADMIN_PAGE,
    MAX_FILTER_BYTES,
    MAX_FILTER_DEPTH,
    MAX_FILTER_NODES,
    MAX_FILTER_VALUES,
    MAX_GRAPH_DEPTH,
    MAX_JOINT_SEEDS,
    MAX_JOINT_TRAVERSAL,
    MAX_POINT_KEYS,
    MAX_POINT_PAGE,
    MAX_RANKED_LIMIT,
    MAX_VALUES_PER_MATCH,
    RESERVED_SOURCE_FILTER_KEY,
    ContextViolation,
    compose_source_key_filter,
    deduplicate_first,
    encode_source_keys_for_filter,
    normalize_joint_weights,
    normalize_rank_fusion_weights,
    require_valid,
    validate_embedding,
    validate_filter,
    validate_idempotency_key,
    validate_identifier,
    validate_joint_weights,
    validate_rank_fusion_weights,
    validate_recall_threshold,
    validate_source_key,
    validate_source_keys,
    validate_uuid,
)

__all__ = [
    "CONTEXT_ERROR_CATALOG",
    "CONTEXT_OPERATION_STAGES",
    "ContextErrorCode",
    "ContextErrorDescriptor",
    "ContextViolation",
    "compose_source_key_filter",
    "MAX_ADMIN_PAGE",
    "MAX_FILTER_BYTES",
    "MAX_FILTER_DEPTH",
    "MAX_FILTER_NODES",
    "MAX_FILTER_VALUES",
    "MAX_GRAPH_DEPTH",
    "MAX_JOINT_SEEDS",
    "MAX_JOINT_TRAVERSAL",
    "MAX_POINT_KEYS",
    "MAX_POINT_PAGE",
    "MAX_RANKED_LIMIT",
    "MAX_VALUES_PER_MATCH",
    "RESERVED_SOURCE_FILTER_KEY",
    "deduplicate_first",
    "encode_source_keys_for_filter",
    "normalize_rank_fusion_weights",
    "normalize_joint_weights",
    "require_valid",
    "validate_embedding",
    "validate_filter",
    "validate_idempotency_key",
    "validate_identifier",
    "validate_rank_fusion_weights",
    "validate_joint_weights",
    "validate_recall_threshold",
    "validate_source_key",
    "validate_source_keys",
    "validate_uuid",
]

for _enum_name in _enums.__all__:
    globals()[_enum_name] = getattr(_enums, _enum_name)
    if _enum_name not in __all__:
        __all__.append(_enum_name)

for _model_name in _models.__all__:
    globals()[_model_name] = getattr(_models, _model_name)
    if _model_name not in __all__:
        __all__.append(_model_name)

del _enum_name, _model_name
