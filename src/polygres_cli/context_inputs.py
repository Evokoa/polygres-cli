from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from polygres_cli._vendor.polygres_lib.context import (
    ContextViolation,
    deduplicate_first,
    validate_embedding,
    validate_filter,
    validate_idempotency_key,
    validate_identifier,
    validate_joint_weights,
    validate_rank_fusion_weights,
    validate_recall_threshold,
    validate_source_keys,
    validate_uuid,
)
from polygres_cli.cli_errors import GENERAL_FAILURE, USAGE, CliError

ModelT = TypeVar("ModelT", bound=BaseModel)


class _DuplicateJsonKey(ValueError):
    """Raised when strict JSON parsing observes the same object key twice."""


def context_read_object(
    value: str,
    *,
    file_input: bool,
    code: str = "CONTEXT_REQUEST_FILE_INVALID",
    allow_stdin: bool = False,
) -> dict[str, Any]:
    payload = _context_read_json(
        value,
        file_input=file_input,
        code=code,
        allow_stdin=allow_stdin,
    )
    if not isinstance(payload, dict):
        raise CliError(code, "Context input must contain one JSON object.", exit_code=USAGE)
    return payload


def context_read_array(
    value: str,
    *,
    file_input: bool,
    code: str = "CONTEXT_EMBEDDING_INVALID",
) -> list[Any]:
    payload = _context_read_json(value, file_input=file_input, code=code, allow_stdin=False)
    if not isinstance(payload, list):
        raise CliError(code, "Embedding input must contain one JSON array.", exit_code=USAGE)
    return payload


def _context_read_json(
    value: str,
    *,
    file_input: bool,
    code: str,
    allow_stdin: bool,
) -> Any:
    if file_input:
        if value == "-":
            if not allow_stdin:
                raise CliError(
                    code,
                    "Standard input is not supported for this flag.",
                    exit_code=USAGE,
                )
            try:
                stream = getattr(sys.stdin, "buffer", sys.stdin)
                raw = stream.read()
                if isinstance(raw, str):
                    raw = raw.encode("utf-8")
            except OSError as exc:
                raise CliError(
                    code,
                    "Could not read Context input from standard input.",
                    exit_code=USAGE,
                ) from exc
        else:
            path = Path(value)
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise CliError(
                    code,
                    f"Could not read Context input file: {path}",
                    exit_code=USAGE,
                ) from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CliError(code, "Context input must be valid UTF-8.", exit_code=USAGE) from exc
    else:
        text = value
    try:
        return json.loads(
            text,
            parse_constant=lambda constant: _raise_invalid_constant(constant),
            object_pairs_hook=_unique_object,
        )
    except (_DuplicateJsonKey, json.JSONDecodeError, ValueError) as exc:
        raise CliError(
            code,
            "Context input must be one valid JSON value.",
            exit_code=USAGE,
        ) from exc


def _raise_invalid_constant(value: str) -> None:
    raise ValueError(f"non-standard numeric constant: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def context_model_payload(
    model: type[ModelT],
    payload: dict[str, Any],
    *,
    code: str = "CONTEXT_REQUEST_INVALID",
    exclude_unset: bool = False,
) -> dict[str, Any]:
    try:
        validated = model.model_validate(payload)
    except ValidationError as exc:
        errors = [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "rule": item["type"],
            }
            for item in exc.errors(include_url=False, include_context=False, include_input=False)
        ]
        raise CliError(
            code,
            "Context request validation failed.",
            exit_code=USAGE,
            details={"violations": errors[:20]},
        ) from exc
    return validated.model_dump(
        mode="json",
        by_alias=True,
        exclude_unset=exclude_unset,
    )


def context_response_model(model: type[ModelT], payload: dict[str, Any]) -> ModelT:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        errors = [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "rule": item["type"],
            }
            for item in exc.errors(include_url=False, include_context=False, include_input=False)
        ]
        request_id = payload.get("request_id")
        raise CliError(
            "CONTEXT_RESPONSE_INVALID",
            "Context response validation failed.",
            exit_code=GENERAL_FAILURE,
            details={"violations": errors[:20]},
            request_id=str(request_id) if request_id else None,
        ) from exc


def context_validate_uuid(value: str, *, field: str) -> str:
    _raise_violations(
        validate_uuid(value, field=field),
        code="CONTEXT_REQUEST_INVALID",
        message=f"{field.replace('_', ' ').capitalize()} must be a UUID.",
    )
    return value


def context_validate_identifier(value: str, *, field: str) -> str:
    _raise_violations(
        validate_identifier(value, field=field),
        code="CONTEXT_IDENTIFIER_INVALID",
        message=f"{field.replace('_', ' ').capitalize()} is not a valid Context identifier.",
    )
    return value


def context_validate_source_keys(values: list[str]) -> list[str]:
    normalized, violations = validate_source_keys(values)
    _raise_violations(
        violations,
        code="CONTEXT_POINT_KEY_INVALID",
        message="One or more Context source keys are invalid.",
    )
    return normalized


def context_validate_embedding(value: object) -> list[float | int]:
    violations = validate_embedding(value)
    _raise_violations(
        violations,
        code="CONTEXT_EMBEDDING_INVALID",
        message="Embedding must be a non-empty JSON array of finite numbers.",
    )
    assert isinstance(value, list)
    return value


def context_validate_filter(value: object) -> dict[str, Any]:
    violations = validate_filter(value)
    _raise_violations(
        violations,
        code="CONTEXT_FILTER_INVALID",
        message="Context filter is invalid.",
    )
    assert isinstance(value, dict)
    return value


def context_validate_weights(context_weight: object, graph_weight: object) -> None:
    _raise_violations(
        validate_rank_fusion_weights(context_weight, graph_weight),
        code="CONTEXT_RANKING_WEIGHTS_INVALID",
        message="Rank-fusion weights must be finite, non-negative, and not both zero.",
    )


def context_validate_joint_weights(
    semantic_weight: object,
    lexical_weight: object,
    graph_weight: object,
) -> None:
    _raise_violations(
        validate_joint_weights(semantic_weight, lexical_weight, graph_weight),
        code="CONTEXT_RANKING_WEIGHTS_INVALID",
        message="Joint weights must be finite, non-negative, and not all zero.",
    )


def context_validate_recall(value: object) -> float:
    _raise_violations(
        validate_recall_threshold(value),
        code="CONTEXT_REQUEST_INVALID",
        message="Minimum recall must be a finite number from 0 through 1.",
    )
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    return float(value)


def context_idempotency_key(explicit: str | None) -> str:
    value = explicit if explicit is not None else str(uuid4())
    _raise_violations(
        validate_idempotency_key(value),
        code="CONTEXT_IDEMPOTENCY_KEY_INVALID",
        message="Idempotency key must be 1 to 128 printable ASCII characters.",
    )
    return value


def context_parse_jsonb_filters(values: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: dict[str, tuple[str, ...]] = {}
    for value in values:
        key, separator, source = value.partition("=")
        parts = source.split(".") if separator else []
        if not separator or len(parts) < 2:
            raise CliError(
                "CONTEXT_REQUEST_INVALID",
                "--jsonb-filter must use <key>=<column>.<path>[.<path>...].",
                exit_code=USAGE,
            )
        context_validate_identifier(key, field="jsonb_filter.key")
        context_validate_identifier(parts[0], field="jsonb_filter.column")
        for index, segment in enumerate(parts[1:]):
            context_validate_identifier(segment, field=f"jsonb_filter.path.{index}")
        identity = tuple(parts)
        previous = seen.get(key)
        if previous is not None:
            if previous != identity:
                raise CliError(
                    "CONTEXT_REQUEST_INVALID",
                    f"JSONB filter key {key} has conflicting registrations.",
                    exit_code=USAGE,
                )
            continue
        seen[key] = identity
        result.append({"key": key, "column": parts[0], "path": parts[1:]})
    return result


def context_deduplicate(values: list[str]) -> list[str]:
    return deduplicate_first(values)


def context_finite_number(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError("must be a number") from exc
    if not math.isfinite(number):
        raise ValueError("must be finite")
    return number


def _raise_violations(
    violations: tuple[ContextViolation, ...],
    *,
    code: str,
    message: str,
) -> None:
    if not violations:
        return
    raise CliError(
        code,
        message,
        exit_code=USAGE,
        details={
            "violations": [
                {"field": item.field, "rule": item.rule, **item.context} for item in violations[:20]
            ]
        },
    )
