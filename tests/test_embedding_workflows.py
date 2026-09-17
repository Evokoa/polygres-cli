import io
import json

import httpx
import pytest
from test_embeddings_cli import configuration
from test_embeddings_cli import isolated_cli as isolated_cli

from polygres_cli import cli, embedding_workflows
from polygres_cli.cli_errors import CliError

CONFIG = "123e4567-e89b-12d3-a456-426614174000"
BASE = ["--project", "p0123456789abcdef0123456"]


def preview(version=3, eligible=2, retried=0):
    return dict(
        expected_version=version,
        eligible_rows=eligible,
        blocked_rows=1,
        max_input_tokens=8191,
        samples=[],
        retried_rows=retried,
    )


def run(*args, structured=True):
    return cli.main(BASE + (["--json"] if structured else []) + ["embeddings", *args])


class Terminal(io.StringIO):
    def isatty(self):
        return True


def test_recovery_preview_preserves_json_without_mutation(isolated_cli, capsys):
    isolated_cli.return_value = preview()
    assert run("recover-oversized", CONFIG, "--preview") == 0
    assert json.loads(capsys.readouterr().out) == preview()
    isolated_cli.assert_called_once()
    assert isolated_cli.call_args.kwargs["json"] == {"action": "preview_chunking"}


def test_recovery_uses_preview_version_internally(isolated_cli, capsys):
    isolated_cli.side_effect = [preview(47), preview(48, retried=2)]
    assert run("recover-oversized", CONFIG, "--yes") == 0
    calls = isolated_cli.call_args_list
    assert calls[1].kwargs["json"] == {"action": "enable_chunking", "expected_version": 47}
    assert calls[1].kwargs["read_only_retry"] is False
    assert calls[1].kwargs["allow_auth_replay"] is False
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["retried_rows"] == 2


@pytest.mark.parametrize("eligible", [0, 2])
def test_preview_only_or_decline_never_mutates(isolated_cli, monkeypatch, eligible):
    isolated_cli.return_value = preview(eligible=eligible)
    monkeypatch.setattr("sys.stdin", Terminal("no\n"))
    assert run("recover-oversized", CONFIG, structured=False) == 0
    assert isolated_cli.call_count == 1


def test_json_mode_does_not_prompt_even_with_tty(isolated_cli, monkeypatch, capsys):
    isolated_cli.return_value = preview()
    monkeypatch.setattr("sys.stdin", Terminal("yes\n"))
    assert run("recover-oversized", CONFIG) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert isolated_cli.call_count == 1


def conflict():
    return CliError("EMBEDDING_CONFIGURATION_CONFLICT", "conflict", exit_code=6, status_code=409)


def test_interactive_conflict_refreshes_and_reconfirms(isolated_cli, monkeypatch, capsys):
    isolated_cli.side_effect = [preview(3), conflict(), preview(5), preview(6, retried=1)]
    monkeypatch.setattr("sys.stdin", Terminal("yes\nyes\n"))
    assert run("recover-oversized", CONFIG, structured=False) == 0
    assert isolated_cli.call_args.kwargs["json"]["expected_version"] == 5
    assert capsys.readouterr().err.count("Enable automatic chunking and retry") == 2


def test_script_conflict_does_not_resubmit(isolated_cli, capsys):
    isolated_cli.side_effect = [preview(), conflict()]
    assert run("recover-oversized", CONFIG, "--yes") == 6
    assert isolated_cli.call_count == 2
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"] == "EMBEDDING_CONFIGURATION_CONFLICT"
    )


def test_repeated_interactive_conflicts_are_bounded(isolated_cli, monkeypatch):
    isolated_cli.side_effect = [preview(), conflict()] * 3
    monkeypatch.setattr("sys.stdin", Terminal("yes\nyes\nyes\n"))
    assert run("recover-oversized", CONFIG, structured=False) == 6
    assert isolated_cli.call_count == 6


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("timeout"), httpx.ConnectError("lost")])
def test_ambiguous_recovery_is_not_repeated(isolated_cli, capsys, failure):
    isolated_cli.side_effect = [preview(), failure]
    assert run("recover-oversized", CONFIG, "--yes") == 8
    assert isolated_cli.call_count == 2
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"]
        == "EMBEDDING_RECOVERY_OUTCOME_UNCONFIRMED"
    )


def test_invalid_preview_fails_before_confirmation(isolated_cli):
    isolated_cli.return_value = {"status": "current"}
    assert run("recover-oversized", CONFIG, "--yes") == 8
    assert isolated_cli.call_count == 1


def old_server_error(field, kind):
    return CliError(
        "VALIDATION_ERROR",
        "invalid",
        exit_code=2,
        status_code=422,
        details={"errors": [{"loc": ["body", *field], "type": kind}]},
    )


def test_old_server_recovery_rejection_explained(isolated_cli, capsys):
    isolated_cli.side_effect = old_server_error(["action"], "literal_error")
    assert run("recover-oversized", CONFIG, "--yes") == 2
    assert isolated_cli.call_count == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "EMBEDDING_FEATURE_UNSUPPORTED"


def test_other_validation_error_is_not_called_an_old_server(isolated_cli, capsys):
    isolated_cli.side_effect = old_server_error(["model_id"], "uuid_parsing")
    assert run("recover-oversized", CONFIG, "--yes") == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "chunking,enabled",
    [
        ({"mode": "off"}, False),
        ({"mode": "custom", "size_tokens": 256, "overlap_tokens": 32}, True),
        ({"enabled": False}, False),
        ({"enabled": True}, True),
        ({}, False),
    ],
)
def test_explicit_chunking_keeps_legacy_wire_format(isolated_cli, tmp_path, chunking, enabled):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(configuration() | {"chunking": chunking}))
    assert run("create", "--file", str(path)) == 0
    result = isolated_cli.call_args.kwargs["json"]["chunking"]
    assert "mode" not in result
    assert result["enabled"] is enabled


def test_new_default_is_explicit_and_never_downgrades(isolated_cli, tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(configuration()))
    isolated_cli.side_effect = old_server_error(["chunking", "mode"], "extra_forbidden")
    assert run("create", "--file", str(path)) == 2
    assert isolated_cli.call_count == 1
    assert isolated_cli.call_args.kwargs["json"]["chunking"]["mode"] == "automatic"
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "EMBEDDING_FEATURE_UNSUPPORTED"


@pytest.mark.parametrize("action", ["run", "pause", "resume", "retry", "reconcile"])
def test_existing_action_wire_and_output_unchanged(isolated_cli, capsys, action):
    response = {"id": CONFIG, "status": "paused", "future_field": "preserved"}
    isolated_cli.return_value = response
    assert run(action, CONFIG, structured=False) == 0
    assert json.loads(capsys.readouterr().out) == response
    assert isolated_cli.call_args.kwargs["json"] == {"action": action}


def ready(**extra):
    return {
        "status": "current",
        "progress": dict(
            pending=0,
            processing=0,
            failed=0,
            uncertain=0,
            context_pending=0,
            context_failed=0,
            **extra,
        ),
    }


def test_watch_waits_for_index_and_emits_one_json(isolated_cli, monkeypatch, capsys):
    waiting = ready()
    waiting["progress"]["context_pending"] = 10
    isolated_cli.side_effect = [waiting, ready()]
    monkeypatch.setattr(embedding_workflows.time, "sleep", lambda _: None)
    assert run("get", CONFIG, "--watch") == 0
    output = capsys.readouterr()
    assert output.err == "" and json.loads(output.out) == ready()
    assert isolated_cli.call_count == 2


@pytest.mark.parametrize("state", ["paused", "uncertain", "failed", "quota_exhausted"])
def test_watch_action_required(isolated_cli, state):
    value = ready()
    if state in ("uncertain", "failed"):
        value["progress"][state] = 1
    else:
        value["status"] = state
    isolated_cli.return_value = value
    assert run("get", CONFIG, "--watch") == 6
    assert isolated_cli.call_count == 1


def test_watch_does_not_guess_missing_search_status(isolated_cli, monkeypatch, capsys):
    isolated_cli.return_value = {"status": "current", "progress": {}}
    clock = iter([0, 0, 2, 2])
    monkeypatch.setattr(embedding_workflows.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(embedding_workflows.time, "sleep", lambda _: None)
    assert run("get", CONFIG, "--watch", "--timeout", "1") == 8
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "EMBEDDING_WATCH_TIMEOUT"


def test_watch_interrupt_does_not_mutate(isolated_cli, capsys):
    isolated_cli.side_effect = KeyboardInterrupt()
    assert run("get", CONFIG, "--watch") == 130
    assert isolated_cli.call_args.args[2] == "GET"
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "EMBEDDING_WATCH_INTERRUPTED"


def test_summary_is_opt_in_and_missing_counts_are_unknown(isolated_cli, capsys):
    isolated_cli.return_value = {"configurations": [{"id": CONFIG, "status": "current"}]}
    assert run("list", structured=False) == 0
    assert json.loads(capsys.readouterr().out) == isolated_cli.return_value
    assert run("list", "--summary", structured=False) == 0
    assert "Search updates pending: not reported" in capsys.readouterr().out
    assert run("list", "--summary") == 0
    assert json.loads(capsys.readouterr().out) == isolated_cli.return_value


@pytest.mark.parametrize(
    "result",
    [
        {"invalid": True},
        CliError("SERVICE_UNAVAILABLE", "unavailable", exit_code=8, status_code=503),
    ],
)
def test_unconfirmed_server_result_does_not_repeat_mutation(isolated_cli, capsys, result):
    isolated_cli.side_effect = [preview(), result]
    assert run("recover-oversized", CONFIG, "--yes") == 8
    assert isolated_cli.call_count == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == (
        "EMBEDDING_RECOVERY_OUTCOME_UNCONFIRMED"
    )


def test_preview_network_failure_never_submits_recovery(isolated_cli, capsys):
    isolated_cli.side_effect = httpx.ConnectError("unavailable")
    assert run("recover-oversized", CONFIG, "--yes") == 8
    assert isolated_cli.call_count == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "EMBEDDING_PREVIEW_UNAVAILABLE"


def test_recovery_real_transport_never_replays_after_503(capsys):
    from types import SimpleNamespace

    from polygres_cli.runtime_client import RuntimeClient

    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["action"] == "preview_chunking":
            return httpx.Response(200, json=preview(47))
        return httpx.Response(
            503, json={"error": {"code": "SERVICE_UNAVAILABLE", "message": "unavailable"}}
        )

    runtime = RuntimeClient(
        grant_provider=lambda project, scope: {
            "project_id": project,
            "scope": scope,
            "access_token": "test-token",
            "expires_at": "2099-01-01T00:00:00Z",
            "runtime_api_url": f"https://{project}.api.staging.db.polygres.com/v1",
        },
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    ctx = SimpleNamespace(client=SimpleNamespace(_runtime=runtime), json=True, quiet=False)
    args = SimpleNamespace(configuration_id=CONFIG, preview=False, yes=True)
    with pytest.raises(CliError, match="server could not confirm") as error:
        embedding_workflows.recover_oversized(ctx, args, BASE[1])
    assert error.value.code == "EMBEDDING_RECOVERY_OUTCOME_UNCONFIRMED"
    assert calls == [
        {"action": "preview_chunking"},
        {"action": "enable_chunking", "expected_version": 47},
    ]
