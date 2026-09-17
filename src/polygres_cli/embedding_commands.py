"""CLI commands using the same source/configuration contract as Runtime."""

import json
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from polygres_cli._vendor.polygres_lib.embeddings.models import (
    EmbeddingConfigurationCreate,
    EmbeddingConfigurationUpdate,
    EmbeddingRemoveRequest,
)
from polygres_cli.cli_errors import USAGE, CliError
from polygres_cli.context_inputs import context_read_object


def _embedding_payload(model: type[BaseModel], payload: dict[str, Any]) -> dict[str, Any]:
    try:
        validated = model.model_validate(payload)
    except ValidationError as exc:
        violations = [
            {
                "field": ".".join(str(part) for part in item["loc"]) or "configuration",
                "rule": item["type"],
                "message": item["msg"],
            }
            for item in exc.errors(include_url=False, include_context=False, include_input=False)[
                :20
            ]
        ]
        message = "Embedding input validation failed: " + "; ".join(
            f"{item['field']}: {item['message']}" for item in violations
        )
        raise CliError(
            "VALIDATION_ERROR", message, exit_code=USAGE, details={"violations": violations}
        ) from None
    return validated.model_dump(mode="json", exclude_none=True)


def add_parsers(subparsers):
    from polygres_cli.cli import _timeout_seconds

    parser = subparsers.add_parser("embeddings", help="manage automatic embeddings")
    commands = parser.add_subparsers(dest="embedding_action", required=True)
    for name in [
        "sources",
        "models",
        "usage",
        "list",
        "get",
        "preview",
        "create",
        "update",
        "remove",
        "run",
        "pause",
        "resume",
        "retry",
        "reconcile",
        "context",
        "recover-oversized",
    ]:
        command = commands.add_parser(name)
        if name in {
            "get",
            "update",
            "remove",
            "run",
            "pause",
            "resume",
            "retry",
            "reconcile",
            "context",
            "recover-oversized",
        }:
            command.add_argument("configuration_id", type=UUID)
        if name in {"preview", "create", "update"}:
            command.add_argument(
                "--file", required=True, help="JSON configuration file, or - for stdin"
            )
        if name == "create":
            command.add_argument("--idempotency-key", default=None)
        if name in {
            "get",
            "list",
            "preview",
            "create",
            "run",
            "pause",
            "resume",
            "retry",
            "reconcile",
        }:
            command.add_argument(
                "--summary",
                action="store_true",
                help="show a readable summary instead of the existing JSON output",
            )
        if name == "get":
            command.add_argument(
                "--watch",
                action="store_true",
                help="wait for generation and search publication to finish",
            )
            command.add_argument(
                "--timeout",
                type=_timeout_seconds,
                default=600,
                help="watch timeout in seconds (default: 600)",
            )
        if name == "recover-oversized":
            options = command.add_mutually_exclusive_group()
            options.add_argument(
                "--preview",
                action="store_true",
                help="preview eligible failures without changing settings",
            )
            options.add_argument(
                "--yes",
                action="store_true",
                help="enable automatic chunking and retry without prompting",
            )
        if name == "remove":
            command.add_argument("--expected-version", type=int, required=True)
            output = command.add_mutually_exclusive_group(required=True)
            output.add_argument("--keep-output", action="store_true")
            output.add_argument("--delete-output", action="store_true")
        command.set_defaults(func=handle)


def handle(ctx, args):
    from polygres_cli.cli import _resolve_project_id
    from polygres_cli.cli_output import write_json

    project_id = _resolve_project_id(ctx, None)
    action = args.embedding_action
    from polygres_cli.embedding_workflows import recover_oversized, render_summary, watch

    if action == "recover-oversized":
        return recover_oversized(ctx, args, project_id)
    if action == "get" and args.watch:
        return watch(ctx, args, project_id)
    paths = {
        "sources": "/sources",
        "models": "/models",
        "usage": "/usage",
        "list": "/configurations",
        "preview": "/preview",
        "create": "/configurations",
    }
    suffix = paths.get(action, f"/configurations/{getattr(args, 'configuration_id', '')}")
    method = "GET"
    body = None
    if action in {"preview", "create", "update"}:
        contract = (
            EmbeddingConfigurationUpdate if action == "update" else EmbeddingConfigurationCreate
        )
        body = _embedding_payload(
            contract, context_read_object(args.file, file_input=True, allow_stdin=True)
        )
        # These modes have exact legacy representations, accepted by older servers.
        # Automatic must remain explicit and must never silently downgrade to off.
        if body.get("chunking", {}).get("mode") in {"off", "custom"}:
            body["chunking"].pop("mode")
        method = "PATCH" if action == "update" else "POST"
    elif action in {"run", "pause", "resume", "retry", "reconcile"}:
        method = "POST"
        suffix += "/actions"
        body = {"action": action}
    elif action == "context":
        suffix += "/context"
    elif action == "remove":
        method = "DELETE"
        body = _embedding_payload(
            EmbeddingRemoveRequest,
            {
                "expected_version": args.expected_version,
                "delete_managed_output": args.delete_output,
            },
        )
    key = (getattr(args, "idempotency_key", None) or str(uuid4())) if action == "create" else None
    scope = "context:read" if action in {"models", "usage", "list", "get"} else "context:manage"
    from polygres_cli.embedding_workflows import request

    response = request(
        ctx,
        project_id,
        scope,
        method,
        "/embeddings" + suffix,
        json=body,
        headers={"Idempotency-Key": key} if key else None,
        read_only_retry=method == "GET",
        timeout=130,
    )
    if ctx.json:
        write_json(response)
    elif not ctx.quiet:
        if getattr(args, "summary", False):
            print(render_summary(response, action=action, chunking=(body or {}).get("chunking")))
        else:
            print(json.dumps(response, indent=2, ensure_ascii=False))
    return 0
