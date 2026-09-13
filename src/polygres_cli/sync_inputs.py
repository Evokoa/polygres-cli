from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from polygres_cli.cli_errors import USAGE, CliError

ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SYNC_SELECTION_FIELDS = frozenset(
    {
        "schema_name",
        "table_name",
        "sync_key_index_name",
        "destination_key_index_name",
        "included_columns",
    }
)


def build_source_connection(
    *,
    connection_environment: str | None,
    host: str | None,
    port: int | None,
    database: str | None,
    username: str | None,
    password_environment: str | None,
    environment: Mapping[str, str],
    prompt_secret: Callable[[str], str],
    interactive: bool,
) -> dict[str, Any]:
    structured_values = (host, port, database, username, password_environment)
    if connection_environment is not None and any(
        value is not None for value in structured_values
    ):
        raise _usage(
            "--connection-env cannot be combined with structured connection options."
        )
    if connection_environment is not None:
        return {"url": _environment_secret(connection_environment, environment)}

    if any(value is not None for value in structured_values):
        missing = [
            flag
            for flag, value in (
                ("--host", host),
                ("--database", database),
                ("--username", username),
            )
            if value is None
        ]
        if missing:
            raise _usage(
                "Structured connection input requires " + ", ".join(missing) + "."
            )
        if port is not None and not 1 <= port <= 65535:
            raise _usage("Source PostgreSQL port must be between 1 and 65535.")
        if password_environment is not None:
            password = _environment_secret(password_environment, environment)
        elif interactive:
            password = prompt_secret("Source PostgreSQL password: ")
            if not password:
                raise _usage("Source PostgreSQL password cannot be empty.")
        else:
            raise _usage(
                "Structured connection input requires --password-env outside an interactive "
                "terminal."
            )
        return {
            "host": host,
            "port": port or 5432,
            "database": database,
            "username": username,
            "password": password,
        }

    if interactive:
        connection_url = prompt_secret("Source PostgreSQL URL: ")
        if connection_url:
            return {"url": connection_url}
        raise _usage("Source PostgreSQL URL cannot be empty.")
    raise _usage(
        "Provide a source connection with --connection-env, or use --host, --database, "
        "--username, and --password-env."
    )


def sync_idempotency_key(explicit: str | None) -> str:
    value = explicit if explicit is not None else str(uuid4())
    non_printable = any(ord(character) < 32 or ord(character) > 126 for character in value)
    if not 1 <= len(value) <= 128 or non_printable:
        raise CliError(
            "SYNC_IDEMPOTENCY_KEY_INVALID",
            "Idempotency key must be 1 to 128 printable ASCII characters.",
            exit_code=USAGE,
        )
    return value


def sync_stage_idempotency_key(root: str, stage: str) -> str:
    digest = hashlib.sha256(root.encode("ascii")).hexdigest()[:40]
    return f"sync-{stage}-{digest}"


def load_sync_selection(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _usage(f"Selection file must contain valid UTF-8 JSON: {path}") from exc
    if isinstance(value, dict):
        value = value.get("tables")
    if not isinstance(value, list) or not value:
        raise _usage("Selection JSON must be a non-empty array or an object with a tables array.")

    selections: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for position, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise _usage(f"Selection item {position} must be a JSON object.")
        unknown = sorted(set(item) - SYNC_SELECTION_FIELDS)
        if unknown:
            raise _usage(f"Selection item {position} has unsupported fields: {', '.join(unknown)}.")
        schema_name = _postgres_name(item.get("schema_name"), "schema_name", position)
        table_name = _postgres_name(item.get("table_name"), "table_name", position)
        identity = (schema_name, table_name)
        if identity in identities:
            raise _usage(f"Selection contains duplicate table {schema_name}.{table_name}.")
        identities.add(identity)
        selection: dict[str, Any] = {
            "schema_name": schema_name,
            "table_name": table_name,
        }
        for key_field in ("sync_key_index_name", "destination_key_index_name"):
            index_name = item.get(key_field)
            if index_name is not None:
                selection[key_field] = _postgres_name(index_name, key_field, position)
        included_columns = item.get("included_columns")
        if included_columns is not None:
            if not isinstance(included_columns, list) or not included_columns:
                raise _usage(
                    f"Selection item {position} included_columns must be a non-empty array."
                )
            columns = [
                _postgres_name(column, "included_columns", position) for column in included_columns
            ]
            if len(set(columns)) != len(columns):
                raise _usage(f"Selection item {position} has duplicate included_columns.")
            selection["included_columns"] = columns
        selections.append(selection)
    return selections


def automatic_sync_selection(
    requested_tables: list[str], available_tables: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    indexed = {
        (str(table.get("schema_name")), str(table.get("table_name"))): table
        for table in available_tables
    }
    selections: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in requested_tables:
        schema_name, table_name = _parse_table_reference(value)
        identity = (schema_name, table_name)
        if identity in seen:
            raise _usage(f"Table {schema_name}.{table_name} was selected more than once.")
        seen.add(identity)
        table = indexed.get(identity)
        if table is None:
            raise _usage(f"Table {schema_name}.{table_name} was not returned by source inspection.")
        partial = table.get("partial_sync") if isinstance(table.get("partial_sync"), dict) else None
        if not table.get("eligible") and partial is None:
            code = table.get("ineligible_code") or "not eligible"
            raise _usage(f"Table {schema_name}.{table_name} cannot be synchronized: {code}.")

        selection: dict[str, Any] = {
            "schema_name": schema_name,
            "table_name": table_name,
        }
        if not table.get("eligible") and partial is not None:
            included = partial.get("included_columns")
            if not isinstance(included, list) or not included:
                raise _usage(
                    f"Table {schema_name}.{table_name} has no usable partial-sync columns."
                )
            selection["included_columns"] = included

        sync_key = table.get("sync_key") if isinstance(table.get("sync_key"), dict) else None
        if (
            sync_key is None
            or (
                table.get("replica_identity") == "default" and sync_key.get("kind") != "primary_key"
            )
            or table.get("replica_identity") == "nothing"
        ):
            raise _usage(f"Table {schema_name}.{table_name} has no usable source change key.")
        included = selection.get("included_columns")
        if included is not None and not set(sync_key.get("columns", [])).issubset(included):
            raise _usage(f"Table {schema_name}.{table_name} must include the source change key.")
        candidates = [
            candidate
            for candidate in table.get("destination_key_candidates", [])
            if isinstance(candidate, dict)
            and (included is None or set(candidate.get("columns", [])).issubset(included))
        ]
        selected_key = table.get("destination_key")
        if isinstance(selected_key, dict) and any(selected_key == key for key in candidates):
            selection["destination_key_index_name"] = selected_key["index_name"]
        elif len(candidates) == 1:
            selection["destination_key_index_name"] = candidates[0]["index_name"]
        elif len(candidates) > 1:
            raise _usage(
                f"Table {schema_name}.{table_name} has multiple eligible destination keys. "
                "Use --file to set destination_key_index_name. "
                "Source change tracking stays unchanged."
            )
        selections.append(selection)
    return selections


def _environment_secret(name: str, environment: Mapping[str, str]) -> str:
    if not ENVIRONMENT_NAME_RE.fullmatch(name):
        raise _usage(f"Invalid environment variable name: {name}")
    value = environment.get(name)
    if not value:
        raise _usage(f"Environment variable {name} is not set or is empty.")
    return value


def _parse_table_reference(value: str) -> tuple[str, str]:
    if "." in value:
        schema_name, table_name = value.split(".", 1)
    else:
        schema_name, table_name = "public", value
    return (
        _postgres_name(schema_name, "schema name", None),
        _postgres_name(table_name, "table name", None),
    )


def _postgres_name(value: object, field: str, position: int | None) -> str:
    location = f" in selection item {position}" if position is not None else ""
    if not isinstance(value, str) or not value or len(value) > 63:
        raise _usage(f"{field}{location} must be a non-empty string of at most 63 characters.")
    return value


def _usage(message: str) -> CliError:
    return CliError("VALIDATION_ERROR", message, exit_code=USAGE)
