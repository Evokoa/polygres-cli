from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from polygres_cli.cli_client import CliControlPlaneClient, ContextPollResponse
from polygres_cli.cli_errors import (
    CONFLICT,
    GENERAL_FAILURE,
    HTTP_EXIT_CODES,
    UNAVAILABLE,
    CliError,
)

ContextProgressCallback = Callable[[dict[str, Any], bool, bool], None]


def context_poll_interval(
    elapsed_stage_seconds: float,
    *,
    fixed_interval: float | None = None,
) -> float:
    if fixed_interval is not None:
        return fixed_interval
    if elapsed_stage_seconds <= 10:
        return 2.0
    if elapsed_stage_seconds <= 60:
        return 5.0
    if elapsed_stage_seconds <= 300:
        return 15.0
    return 30.0


def context_wait_for_operation(
    client: CliControlPlaneClient,
    *,
    project_id: str,
    operation_id: str,
    timeout_seconds: float,
    poll_interval: float | None = None,
    initial_envelope: dict[str, Any] | None = None,
    progress: ContextProgressCallback | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    started = monotonic()
    deadline = started + timeout_seconds
    response = ContextPollResponse(initial_envelope, None) if initial_envelope is not None else None
    observed_stage: str | None = None
    stage_started = started
    observed_processed: int | None = None

    try:
        while True:
            if response is None:
                response = client.context_operations_get_poll(
                    project_id,
                    operation_id,
                    deadline=deadline,
                )
            envelope = response.envelope
            operation = _operation(envelope, operation_id)
            status = str(operation.get("status") or "")
            if status == "succeeded":
                return envelope
            if status == "failed":
                raise _failed_operation_error(envelope, operation, operation_id)
            if status == "cancelled":
                raise CliError(
                    "CONTEXT_OPERATION_CANCELLED",
                    "Context operation was cancelled.",
                    exit_code=CONFLICT,
                    details={
                        "operation_id": operation_id,
                        "operation_status": "cancelled",
                    },
                    request_id=_operation_request_id(envelope, operation),
                )

            now = monotonic()
            stage = str(operation.get("stage") or "")
            stage_changed = stage != observed_stage
            if stage_changed:
                observed_stage = stage
                stage_started = now
            processed = operation.get("processed_units")
            count_changed = (
                isinstance(processed, int)
                and not isinstance(processed, bool)
                and observed_processed is not None
                and processed > observed_processed
            )
            if isinstance(processed, int) and not isinstance(processed, bool):
                observed_processed = max(observed_processed or 0, processed)
            if progress is not None and (stage_changed or count_changed):
                progress(operation, stage_changed, count_changed)

            delay = response.retry_after_seconds
            if delay is None:
                delay = context_poll_interval(
                    max(now - stage_started, 0.0),
                    fixed_interval=poll_interval,
                )
            remaining = deadline - now
            if remaining <= 0 or delay >= remaining:
                if remaining > 0:
                    sleep(remaining)
                raise _timeout_error(operation_id, envelope)
            sleep(delay)
            response = None
    except KeyboardInterrupt as exc:
        raise CliError(
            "CONTEXT_WAIT_INTERRUPTED",
            f"Stopped waiting for Context operation {operation_id}; it is still running.",
            exit_code=GENERAL_FAILURE,
            details={"operation_id": operation_id},
        ) from exc
    except CliError as exc:
        if exc.code == "TIMEOUT":
            raise _timeout_error(operation_id, response.envelope if response else {}) from exc
        raise


def _operation(envelope: dict[str, Any], operation_id: str) -> dict[str, Any]:
    operation = envelope.get("operation")
    if not isinstance(operation, dict):
        raise CliError(
            "CONTEXT_OPERATION_RESPONSE_INVALID",
            "Context operation response is invalid.",
            details={"operation_id": operation_id},
            request_id=str(envelope.get("request_id") or "") or None,
        )
    returned_id = operation.get("id")
    if returned_id is not None and str(returned_id) != operation_id:
        raise CliError(
            "CONTEXT_OPERATION_RESPONSE_INVALID",
            "Context operation response returned a different operation.",
            details={"operation_id": operation_id},
            request_id=str(envelope.get("request_id") or "") or None,
        )
    return operation


def _failed_operation_error(
    envelope: dict[str, Any],
    operation: dict[str, Any],
    operation_id: str,
) -> CliError:
    failure = operation.get("error")
    if not isinstance(failure, dict):
        return CliError(
            "CONTEXT_OPERATION_FAILED",
            "Context operation failed.",
            exit_code=GENERAL_FAILURE,
            details={
                "operation_id": operation_id,
                "operation_status": "failed",
                "retryable": True,
            },
            request_id=_operation_request_id(envelope, operation),
        )
    status = failure.get("http_status")
    status_code = status if isinstance(status, int) and not isinstance(status, bool) else 500
    details = failure.get("details")
    safe_details = dict(details) if isinstance(details, dict) else {}
    safe_details.setdefault("operation_id", operation_id)
    safe_details["operation_status"] = "failed"
    if isinstance(failure.get("retryable"), bool):
        safe_details["retryable"] = failure["retryable"]
    return CliError(
        str(failure.get("code") or "CONTEXT_OPERATION_FAILED"),
        str(failure.get("message") or "Context operation failed."),
        exit_code=HTTP_EXIT_CODES.get(status_code, GENERAL_FAILURE),
        details=safe_details,
        request_id=_operation_request_id(envelope, operation),
    )


def _timeout_error(operation_id: str, envelope: dict[str, Any]) -> CliError:
    return CliError(
        "CONTEXT_OPERATION_TIMEOUT",
        f"Timed out waiting for Context operation {operation_id}; it is still running.",
        exit_code=UNAVAILABLE,
        details={"operation_id": operation_id},
        request_id=str(envelope.get("request_id") or "") or None,
    )


def _operation_request_id(envelope: dict[str, Any], operation: dict[str, Any]) -> str | None:
    value = operation.get("request_id") or envelope.get("request_id")
    return str(value) if value else None
