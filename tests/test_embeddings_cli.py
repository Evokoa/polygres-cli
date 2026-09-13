import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from polygres_cli import cli
from polygres_cli.runtime_client import RuntimeClient


def test_search_command_is_not_available(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("POLYGRES_CONFIG_PATH", str(tmp_path / "config.json"))

    def unexpected_request(*args, **kwargs):
        raise AssertionError("Removed command must not send a Runtime request")

    monkeypatch.setattr(RuntimeClient, "request", unexpected_request)
    assert cli.main(["embeddings", "search"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_removal_requires_explicit_output_choice(monkeypatch, tmp_path):
    monkeypatch.setenv("POLYGRES_CONFIG_PATH", str(tmp_path / "config.json"))
    assert (
        cli.main(
            [
                "--project",
                "p0123456789abcdef0123456",
                "embeddings",
                "remove",
                str(uuid4()),
                "--expected-version",
                "1",
            ]
        )
        == 2
    )


@pytest.fixture
def isolated_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("POLYGRES_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.delenv("POLYGRES_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(cli, "_display_post_command_notices", lambda **kwargs: None)
    request = Mock(return_value={"status": "accepted"})
    monkeypatch.setattr(RuntimeClient, "request", request)
    return request


def configuration():
    return {
        "name": "Documents",
        "source_schema": "public",
        "source_table": "docs",
        "source_key_columns": ["id"],
        "source_text_column": "body",
        "model_id": str(uuid4()),
        "dimensions": 256,
    }


def command(tmp_path, action, payload, json_output):
    args = ["--project", "p0123456789abcdef0123456"]
    if json_output:
        args.append("--json")
    args.extend(["embeddings", action])
    if action in {"update", "remove"}:
        args.append("123e4567-e89b-12d3-a456-426614174000")
    if action == "remove":
        args.extend(["--expected-version", str(payload["expected_version"]), "--keep-output"])
    else:
        path = tmp_path / "embedding.json"
        path.write_text(json.dumps(payload))
        args.extend(["--file", str(path)])
    return args


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize(
    "action,payload,field",
    [
        ("preview", {}, "source_table"),
        ("create", {}, "source_table"),
        ("preview", configuration() | {"batch_size": 5}, "batch_size"),
        (
            "create",
            configuration()
            | {
                "chunking": {
                    "enabled": True,
                    "size_tokens": 32,
                    "overlap_tokens": 32,
                }
            },
            "chunking",
        ),
        ("create", configuration() | {"model_id": "sensitive-invalid-value"}, "model_id"),
        ("update", {}, "expected_version"),
        ("update", {"expected_version": 1, "source_table": "other"}, "source_table"),
        ("update", {"expected_version": 1, "model_id": str(uuid4())}, "model_id"),
        ("update", {"expected_version": 0}, "expected_version"),
        ("remove", {"expected_version": 0}, "expected_version"),
    ],
)
def test_invalid_embedding_inputs_use_cli_error_contract(
    isolated_cli, tmp_path, capsys, action, payload, field, json_output
):
    assert cli.main(command(tmp_path, action, payload, json_output)) == 2
    captured = capsys.readouterr()
    isolated_cli.assert_not_called()
    output = captured.out + captured.err
    assert "Traceback" not in output
    assert "sensitive-invalid-value" not in output
    assert field in output
    if json_output:
        assert captured.err == ""
        error = json.loads(captured.out)["error"]
        assert error["code"] == "VALIDATION_ERROR"
        violations = error["details"]["violations"]
        assert any(item["field"] == field for item in violations)
        assert all(set(item) == {"field", "rule", "message"} for item in violations)
    else:
        assert captured.out == ""
        assert "Embedding input validation failed" in captured.err


@pytest.mark.parametrize(
    "action,payload,method,suffix",
    [
        ("preview", configuration(), "POST", "/preview"),
        ("create", configuration(), "POST", "/configurations"),
        (
            "update",
            {"expected_version": 1, "name": "Renamed"},
            "PATCH",
            "/configurations/123e4567-e89b-12d3-a456-426614174000",
        ),
        (
            "remove",
            {"expected_version": 1},
            "DELETE",
            "/configurations/123e4567-e89b-12d3-a456-426614174000",
        ),
    ],
)
def test_valid_embedding_inputs_still_reach_runtime(
    isolated_cli, tmp_path, capsys, action, payload, method, suffix
):
    assert cli.main(command(tmp_path, action, payload, True)) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "accepted"}
    isolated_cli.assert_called_once()
    call = isolated_cli.call_args
    assert call.args[2:] == (method, "/embeddings" + suffix)
    if action == "remove":
        assert call.kwargs["json"] == {"expected_version": 1, "delete_managed_output": False}
    elif action == "update":
        assert call.kwargs["json"] == payload
    else:
        assert all(call.kwargs["json"][key] == value for key, value in payload.items())
    assert bool(call.kwargs["headers"]) == (action == "create")


def test_unexpected_embedding_failures_are_not_reported_as_invalid_input(
    isolated_cli, monkeypatch, tmp_path
):
    from polygres_cli import embedding_commands

    def broken_validation(*args, **kwargs):
        raise RuntimeError("unexpected implementation failure")

    monkeypatch.setattr(
        embedding_commands.EmbeddingConfigurationCreate, "model_validate", broken_validation
    )
    with pytest.raises(RuntimeError, match="unexpected implementation failure"):
        cli.main(command(tmp_path, "preview", configuration(), True))
    isolated_cli.assert_not_called()
