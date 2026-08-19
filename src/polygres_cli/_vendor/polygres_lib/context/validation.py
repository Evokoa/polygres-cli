from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RELATIONSHIP_TYPE_PATTERN = IDENTIFIER_PATTERN
RESERVED_SOURCE_FILTER_KEY = "__polygres_source_id"

MAX_IDENTIFIER_BYTES = 63
MAX_SOURCE_KEY_BYTES = 1_024
MAX_POINT_KEYS = 10_000
MAX_ADMIN_PAGE = 100
MAX_POINT_PAGE = 100
MAX_RANKED_LIMIT = 1_000
MAX_GRAPH_DEPTH = 20
MAX_JOINT_SEEDS = 32
MAX_JOINT_TRAVERSAL = 1_000
MAX_FILTER_BYTES = 65_536
MAX_FILTER_DEPTH = 16
MAX_FILTER_NODES = 256
MAX_FILTER_VALUES = 2_000
MAX_VALUES_PER_MATCH = 1_000
MAX_FILTER_KEY_BYTES = 512
MAX_IDEMPOTENCY_KEY_CHARS = 128

_SOURCE_KEY_INTEGER_BOUNDS = {
    "smallint": (-(2**15), 2**15 - 1),
    "integer": (-(2**31), 2**31 - 1),
    "bigint": (-(2**63), 2**63 - 1),
}


@dataclass(frozen=True, slots=True)
class ContextViolation:
    field: str
    rule: str
    context: dict[str, int | str]


def validate_identifier(value: str, *, field: str = "identifier") -> tuple[ContextViolation, ...]:
    violations = []
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        violations.append(ContextViolation(field, "ascii_sql_identifier", {}))
    elif len(value.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        violations.append(
            ContextViolation(field, "max_utf8_bytes", {"limit": MAX_IDENTIFIER_BYTES})
        )
    return tuple(violations)


def validate_uuid(value: str, *, field: str) -> tuple[ContextViolation, ...]:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError):
        return (ContextViolation(field, "uuid", {}),)
    if str(parsed) != value.lower():
        return (ContextViolation(field, "canonical_uuid", {}),)
    return ()


def validate_source_key(value: str, *, field: str) -> tuple[ContextViolation, ...]:
    if not isinstance(value, str):
        return (ContextViolation(field, "string", {}),)
    violations = []
    if not value:
        violations.append(ContextViolation(field, "non_empty", {}))
    if "\x00" in value:
        violations.append(ContextViolation(field, "no_nul", {}))
    if len(value.encode("utf-8")) > MAX_SOURCE_KEY_BYTES:
        violations.append(
            ContextViolation(field, "max_utf8_bytes", {"limit": MAX_SOURCE_KEY_BYTES})
        )
    return tuple(violations)


def deduplicate_first(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def validate_source_keys(
    values: object, *, field: str = "source_keys"
) -> tuple[list[str], tuple[ContextViolation, ...]]:
    if not isinstance(values, list) or not values:
        return [], (ContextViolation(field, "non_empty_array", {}),)
    unique = deduplicate_first(values) if all(isinstance(item, str) for item in values) else values
    violations: list[ContextViolation] = []
    if len(unique) > MAX_POINT_KEYS:
        violations.append(ContextViolation(field, "max_items", {"limit": MAX_POINT_KEYS}))
    for index, value in enumerate(unique):
        violations.extend(validate_source_key(value, field=f"{field}.{index}"))
    return list(unique), tuple(violations)


def encode_source_keys_for_filter(
    values: object,
    source_key_type: str,
    *,
    field: str = "source_keys",
) -> tuple[list[str | int], tuple[ContextViolation, ...]]:
    """Validate source keys and encode their JSON scalar type for pgContext filters."""
    normalized, violations = validate_source_keys(values, field=field)
    if violations:
        return [], violations

    key_type = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", source_key_type).strip().lower()
    if key_type == "varchar":
        key_type = "character varying"
    if key_type in {"text", "character varying"}:
        return normalized, ()

    encoded: list[str | int] = []
    errors: list[ContextViolation] = []
    for index, value in enumerate(normalized):
        item_field = f"{field}.{index}"
        if key_type == "uuid":
            try:
                encoded.append(str(UUID(value)))
            except (TypeError, ValueError, AttributeError):
                errors.append(ContextViolation(item_field, "uuid", {}))
            continue
        bounds = _SOURCE_KEY_INTEGER_BOUNDS.get(key_type)
        if bounds is None:
            return [], (
                ContextViolation(field, "certified_source_key_type", {"type": source_key_type}),
            )
        if not re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
            errors.append(ContextViolation(item_field, "canonical_integer", {}))
            continue
        number = int(value)
        if not bounds[0] <= number <= bounds[1]:
            errors.append(
                ContextViolation(
                    item_field,
                    "integer_range",
                    {"minimum": bounds[0], "maximum": bounds[1]},
                )
            )
            continue
        encoded.append(number)

    if errors:
        return [], tuple(errors)
    if len(set(encoded)) != len(encoded):
        return [], (ContextViolation(field, "canonical_collision", {}),)
    return encoded, ()


def compose_source_key_filter(
    public_filter: dict[str, object] | None,
    source_keys: list[str | int],
    *,
    field: str = "filter",
) -> tuple[dict[str, object], tuple[ContextViolation, ...]]:
    """Compose the one private source-key condition and recheck aggregate budgets."""
    source = {"key": RESERVED_SOURCE_FILTER_KEY, "match": {"any": source_keys}}
    combined: dict[str, object] = {"must": [source]}
    if public_filter is not None:
        combined["must"] = [source, *public_filter.get("must", [])]
        for lane in ("should", "must_not"):
            if public_filter.get(lane):
                combined[lane] = public_filter[lane]
    reserved_field = f"{field}.must.0.key"
    violations = tuple(
        violation
        for violation in validate_filter(combined, field=field)
        if not (violation.field == reserved_field and violation.rule == "reserved")
    )
    return combined, violations


def validate_idempotency_key(
    value: str, *, field: str = "Idempotency-Key"
) -> tuple[ContextViolation, ...]:
    if not isinstance(value, str) or not value:
        return (ContextViolation(field, "required", {}),)
    if len(value) > MAX_IDEMPOTENCY_KEY_CHARS:
        return (ContextViolation(field, "max_characters", {"limit": MAX_IDEMPOTENCY_KEY_CHARS}),)
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in value):
        return (ContextViolation(field, "printable_ascii", {}),)
    return ()


def validate_embedding(
    value: object,
    *,
    field: str = "embedding",
    expected_dimensions: int | None = None,
    metric: str | None = None,
) -> tuple[ContextViolation, ...]:
    if not isinstance(value, list) or not value:
        return (ContextViolation(field, "non_empty_numeric_array", {}),)
    for index, item in enumerate(value):
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
        ):
            return (ContextViolation(f"{field}.{index}", "finite_number", {}),)
    if expected_dimensions is not None and len(value) != expected_dimensions:
        return (
            ContextViolation(
                field,
                "dimensions",
                {"expected": expected_dimensions, "actual": len(value)},
            ),
        )
    if metric == "cosine" and not any(float(item) != 0.0 for item in value):
        return (ContextViolation(field, "non_zero_cosine", {"metric": metric}),)
    return ()


def validate_rank_fusion_weights(
    context_weight: object, graph_weight: object
) -> tuple[ContextViolation, ...]:
    values = (("weights.context", context_weight), ("weights.graph", graph_weight))
    violations = []
    for field, value in values:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            violations.append(ContextViolation(field, "finite_non_negative", {}))
    if not violations and float(context_weight) == 0 and float(graph_weight) == 0:
        violations.append(ContextViolation("weights", "at_least_one_positive", {}))
    return tuple(violations)


def normalize_rank_fusion_weights(
    context_weight: float, graph_weight: float
) -> tuple[float, float]:
    violations = validate_rank_fusion_weights(context_weight, graph_weight)
    if violations:
        raise ValueError(violations[0].rule)
    total = context_weight + graph_weight
    return context_weight / total, graph_weight / total


def validate_joint_weights(
    semantic_weight: object,
    lexical_weight: object,
    graph_weight: object,
) -> tuple[ContextViolation, ...]:
    values = (
        ("weights.semantic", semantic_weight),
        ("weights.lexical", lexical_weight),
        ("weights.graph", graph_weight),
    )
    violations = []
    for field, value in values:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            violations.append(ContextViolation(field, "finite_non_negative", {}))
    if not violations and all(float(value) == 0 for _, value in values):
        violations.append(ContextViolation("weights", "at_least_one_positive", {}))
    return tuple(violations)


def normalize_joint_weights(
    semantic_weight: float,
    lexical_weight: float,
    graph_weight: float,
) -> tuple[float, float, float]:
    violations = validate_joint_weights(semantic_weight, lexical_weight, graph_weight)
    if violations:
        raise ValueError(violations[0].rule)
    total = semantic_weight + lexical_weight + graph_weight
    return (
        semantic_weight / total,
        lexical_weight / total,
        graph_weight / total,
    )


def validate_recall_threshold(value: object) -> tuple[ContextViolation, ...]:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= 1
    ):
        return (ContextViolation("minimum_recall", "range_0_1", {}),)
    return ()


def validate_filter(
    value: object,
    *,
    field: str = "filter",
    registered_keys: set[str] | None = None,
) -> tuple[ContextViolation, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict) or not value:
        return (ContextViolation(field, "non_empty_object", {}),)
    violations: list[ContextViolation] = []
    if set(value) - {"must", "should", "must_not"}:
        violations.append(ContextViolation(field, "allowed_keys", {}))
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_FILTER_BYTES:
        violations.append(ContextViolation(field, "max_utf8_bytes", {"limit": MAX_FILTER_BYTES}))
    budget = {"nodes": 0, "values": 0, "depth": 1}
    for lane, conditions in value.items():
        lane_field = f"{field}.{lane}"
        if lane not in {"must", "should", "must_not"}:
            continue
        if not isinstance(conditions, list) or not conditions:
            violations.append(ContextViolation(lane_field, "non_empty_array", {}))
            continue
        for index, condition in enumerate(conditions):
            _validate_condition(
                condition,
                field=f"{lane_field}.{index}",
                registered_keys=registered_keys,
                violations=violations,
                budget=budget,
            )
    if budget["nodes"] > MAX_FILTER_NODES:
        violations.append(ContextViolation(field, "max_nodes", {"limit": MAX_FILTER_NODES}))
    if budget["values"] > MAX_FILTER_VALUES:
        violations.append(ContextViolation(field, "max_values", {"limit": MAX_FILTER_VALUES}))
    if budget["depth"] > MAX_FILTER_DEPTH:
        violations.append(ContextViolation(field, "max_depth", {"limit": MAX_FILTER_DEPTH}))
    return tuple(violations)


def _validate_condition(
    condition: object,
    *,
    field: str,
    registered_keys: set[str] | None,
    violations: list[ContextViolation],
    budget: dict[str, int],
) -> None:
    budget["nodes"] += 1
    if not isinstance(condition, dict):
        violations.append(ContextViolation(field, "object", {}))
        return
    key = condition.get("key")
    if not isinstance(key, str):
        violations.append(ContextViolation(f"{field}.key", "string", {}))
    else:
        violations.extend(validate_identifier(key, field=f"{field}.key"))
        if key == RESERVED_SOURCE_FILTER_KEY:
            violations.append(ContextViolation(f"{field}.key", "reserved", {}))
        if registered_keys is not None and key not in registered_keys:
            violations.append(ContextViolation(f"{field}.key", "registered", {}))
    operators = set(condition) - {"key"}
    if len(operators) != 1 or not operators <= {"match", "range", "is_null", "is_empty"}:
        violations.append(ContextViolation(field, "exactly_one_operator", {}))
        return
    operator = next(iter(operators))
    operand = condition[operator]
    if operator == "match":
        _validate_match(operand, field=f"{field}.match", violations=violations, budget=budget)
    elif operator == "range":
        if (
            not isinstance(operand, dict)
            or not operand
            or set(operand) - {"gt", "gte", "lt", "lte"}
        ):
            violations.append(ContextViolation(f"{field}.range", "range_object", {}))
        else:
            for name, scalar in operand.items():
                if not _is_scalar(scalar):
                    violations.append(ContextViolation(f"{field}.range.{name}", "scalar", {}))
                else:
                    budget["values"] += 1
    elif not isinstance(operand, bool):
        violations.append(ContextViolation(f"{field}.{operator}", "boolean", {}))


def _validate_match(
    value: object,
    *,
    field: str,
    violations: list[ContextViolation],
    budget: dict[str, int],
) -> None:
    if _is_scalar(value):
        budget["values"] += 1
        return
    if not isinstance(value, dict) or len(value) != 1:
        violations.append(ContextViolation(field, "match_shape", {}))
        return
    operator, operand = next(iter(value.items()))
    if operator == "value" and _is_scalar(operand):
        budget["values"] += 1
        return
    if operator in {"any", "except"} and isinstance(operand, list) and operand:
        if len(operand) > MAX_VALUES_PER_MATCH:
            violations.append(
                ContextViolation(field, "max_values_per_match", {"limit": MAX_VALUES_PER_MATCH})
            )
        for index, scalar in enumerate(operand):
            if not _is_scalar(scalar):
                violations.append(ContextViolation(f"{field}.{operator}.{index}", "scalar", {}))
        budget["values"] += len(operand)
        return
    violations.append(ContextViolation(field, "match_shape", {}))


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def require_valid(violations: tuple[ContextViolation, ...]) -> None:
    if violations:
        first = violations[0]
        raise ValueError(f"{first.field}: {first.rule}")


__all__ = [
    "ContextViolation",
    "MAX_ADMIN_PAGE",
    "MAX_FILTER_BYTES",
    "MAX_FILTER_DEPTH",
    "MAX_FILTER_NODES",
    "MAX_FILTER_VALUES",
    "MAX_GRAPH_DEPTH",
    "MAX_JOINT_SEEDS",
    "MAX_JOINT_TRAVERSAL",
    "MAX_IDEMPOTENCY_KEY_CHARS",
    "MAX_POINT_KEYS",
    "MAX_POINT_PAGE",
    "MAX_RANKED_LIMIT",
    "MAX_SOURCE_KEY_BYTES",
    "MAX_VALUES_PER_MATCH",
    "RESERVED_SOURCE_FILTER_KEY",
    "deduplicate_first",
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
