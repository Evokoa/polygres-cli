from __future__ import annotations

import json

import pytest

from polygres_cli.cli_errors import CliError
from polygres_cli.cli_output import write_error


def _operation_error() -> CliError:
    return CliError(
        "CONTEXT_COLLECTION_SYNC_FAILED",
        "Context collection sync failed. Retry the operation.",
        details={
            "failure_stage": "syncing_points",
            "operation_id": "00000000-0000-0000-0000-000000000001",
        },
        request_id="req_test",
    )


def test_human_operation_error_includes_code_stage_and_recovery_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_error(_operation_error(), json_output=False)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Context collection sync failed. Retry the operation. "
        "(error_code: CONTEXT_COLLECTION_SYNC_FAILED, failure_stage: syncing_points, "
        "operation_id: 00000000-0000-0000-0000-000000000001) "
        "(request_id: req_test)\n"
    )


def test_json_operation_error_keeps_structured_failure_details(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_error(_operation_error(), json_output=True)

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "CONTEXT_COLLECTION_SYNC_FAILED",
            "details": {
                "failure_stage": "syncing_points",
                "operation_id": "00000000-0000-0000-0000-000000000001",
            },
            "message": "Context collection sync failed. Retry the operation.",
        },
        "request_id": "req_test",
    }
