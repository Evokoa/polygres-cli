from __future__ import annotations

from typing import Any

import pytest

from polygres_cli.cli_client import ContextPollResponse
from polygres_cli.cli_errors import CliError
from polygres_cli.context_wait import context_poll_interval, context_wait_for_operation

PROJECT_ID = "p0123456789abcdef0123456"
OPERATION_ID = "123e4567-e89b-12d3-a456-426614174000"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeClient:
    def __init__(self, responses: list[ContextPollResponse]) -> None:
        self.responses = responses
        self.calls = 0

    def context_operations_get_poll(
        self,
        project_id: str,
        operation_id: str,
        *,
        deadline: float | None = None,
    ) -> ContextPollResponse:
        assert project_id == PROJECT_ID
        assert operation_id == OPERATION_ID
        assert deadline is not None
        self.calls += 1
        return self.responses.pop(0)


def envelope(
    status: str,
    stage: str,
    *,
    processed: int = 0,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "request_id": f"req_{stage}",
        "operation": {
            "id": OPERATION_ID,
            "status": status,
            "stage": stage,
            "processed_units": processed,
            "total_units": 10,
            "error": error,
        },
    }


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [(0, 2), (10, 2), (10.01, 5), (60, 5), (60.01, 15), (300, 15), (301, 30)],
)
def test_context_poll_interval_boundaries(elapsed: float, expected: float) -> None:
    assert context_poll_interval(elapsed) == expected
    assert context_poll_interval(elapsed, fixed_interval=0.5) == 0.5


def test_wait_uses_initial_state_and_adaptive_stage_reset() -> None:
    clock = FakeClock()
    client = FakeClient(
        [
            ContextPollResponse(envelope("running", "building_index", processed=2), None),
            ContextPollResponse(envelope("running", "verifying", processed=2), None),
            ContextPollResponse(envelope("succeeded", "ready", processed=10), None),
        ]
    )
    progress: list[tuple[str, bool, bool]] = []

    result = context_wait_for_operation(
        client,  # type: ignore[arg-type]
        project_id=PROJECT_ID,
        operation_id=OPERATION_ID,
        timeout_seconds=30,
        initial_envelope=envelope("queued", "queued"),
        progress=lambda operation, stage, count: progress.append(
            (str(operation["stage"]), stage, count)
        ),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result["operation"]["status"] == "succeeded"
    assert client.calls == 3
    assert clock.sleeps == [2, 2, 2]
    assert [item[0] for item in progress] == ["queued", "building_index", "verifying"]


def test_direct_wait_gets_immediately_and_retry_after_overrides_schedule() -> None:
    clock = FakeClock()
    client = FakeClient(
        [
            ContextPollResponse(envelope("running", "working"), 7),
            ContextPollResponse(envelope("succeeded", "ready"), None),
        ]
    )

    result = context_wait_for_operation(
        client,  # type: ignore[arg-type]
        project_id=PROJECT_ID,
        operation_id=OPERATION_ID,
        timeout_seconds=30,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result["operation"]["status"] == "succeeded"
    assert client.calls == 2
    assert clock.sleeps == [7]


def test_fixed_poll_interval_replaces_adaptive_schedule() -> None:
    clock = FakeClock()
    client = FakeClient(
        [
            ContextPollResponse(envelope("running", "working"), None),
            ContextPollResponse(envelope("succeeded", "ready"), None),
        ]
    )

    result = context_wait_for_operation(
        client,  # type: ignore[arg-type]
        project_id=PROJECT_ID,
        operation_id=OPERATION_ID,
        timeout_seconds=30,
        poll_interval=0.5,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result["operation"]["status"] == "succeeded"
    assert clock.sleeps == [0.5]


def test_committed_count_changes_do_not_reset_adaptive_stage_elapsed_time() -> None:
    clock = FakeClock()
    client = FakeClient(
        [
            ContextPollResponse(
                envelope("running", "working", processed=processed),
                None,
            )
            for processed in range(1, 7)
        ]
        + [ContextPollResponse(envelope("succeeded", "ready", processed=10), None)]
    )

    result = context_wait_for_operation(
        client,  # type: ignore[arg-type]
        project_id=PROJECT_ID,
        operation_id=OPERATION_ID,
        timeout_seconds=30,
        initial_envelope=envelope("running", "working"),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result["operation"]["status"] == "succeeded"
    assert clock.sleeps == [2, 2, 2, 2, 2, 2, 5]


def test_retry_after_is_bounded_by_the_remaining_deadline() -> None:
    clock = FakeClock()
    client = FakeClient([ContextPollResponse(envelope("running", "working"), 10)])

    with pytest.raises(CliError) as exc_info:
        context_wait_for_operation(
            client,  # type: ignore[arg-type]
            project_id=PROJECT_ID,
            operation_id=OPERATION_ID,
            timeout_seconds=3,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert exc_info.value.code == "CONTEXT_OPERATION_TIMEOUT"
    assert clock.sleeps == [3]
    assert client.calls == 1


def test_direct_wait_returns_terminal_first_poll_without_sleep() -> None:
    clock = FakeClock()
    terminal = envelope("succeeded", "ready", processed=10)
    client = FakeClient([ContextPollResponse(terminal, None)])

    result = context_wait_for_operation(
        client,  # type: ignore[arg-type]
        project_id=PROJECT_ID,
        operation_id=OPERATION_ID,
        timeout_seconds=30,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result == terminal
    assert client.calls == 1
    assert clock.sleeps == []


def test_wait_interruption_does_not_call_cancel() -> None:
    client = FakeClient([ContextPollResponse(envelope("running", "working"), None)])

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    with pytest.raises(CliError) as exc_info:
        context_wait_for_operation(
            client,  # type: ignore[arg-type]
            project_id=PROJECT_ID,
            operation_id=OPERATION_ID,
            timeout_seconds=30,
            sleep=interrupt,
        )

    assert exc_info.value.code == "CONTEXT_WAIT_INTERRUPTED"
    assert exc_info.value.exit_code == 1
    assert client.calls == 1


def test_wait_timeout_does_not_cancel() -> None:
    clock = FakeClock()
    client = FakeClient([ContextPollResponse(envelope("running", "working"), None)])

    with pytest.raises(CliError) as exc_info:
        context_wait_for_operation(
            client,  # type: ignore[arg-type]
            project_id=PROJECT_ID,
            operation_id=OPERATION_ID,
            timeout_seconds=2,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert exc_info.value.code == "CONTEXT_OPERATION_TIMEOUT"
    assert exc_info.value.exit_code == 8
    assert client.calls == 1
    assert clock.sleeps == [2]


@pytest.mark.parametrize(
    ("status", "error", "code", "exit_code"),
    [
        ("cancelled", None, "CONTEXT_OPERATION_CANCELLED", 6),
        (
            "failed",
            {
                "code": "CONTEXT_IDEMPOTENCY_CONFLICT",
                "message": "Conflict.",
                "details": {"field": "Idempotency-Key"},
                "http_status": 409,
            },
            "CONTEXT_IDEMPOTENCY_CONFLICT",
            6,
        ),
    ],
)
def test_wait_terminal_errors(
    status: str,
    error: dict[str, Any] | None,
    code: str,
    exit_code: int,
) -> None:
    client = FakeClient([])

    with pytest.raises(CliError) as exc_info:
        context_wait_for_operation(
            client,  # type: ignore[arg-type]
            project_id=PROJECT_ID,
            operation_id=OPERATION_ID,
            timeout_seconds=30,
            initial_envelope=envelope(status, status, error=error),
        )

    assert exc_info.value.code == code
    assert exc_info.value.exit_code == exit_code
    assert exc_info.value.details["operation_id"] == OPERATION_ID
    assert exc_info.value.details["operation_status"] == status
    if status == "failed" and error is None:
        assert exc_info.value.details["retryable"] is True
    assert client.calls == 0
