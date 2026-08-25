from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from polygres_cli._vendor.polygres_lib.context import (
    CollectionCreateRequest,
    CollectionUpdateRequest,
    ContextJointResponse,
    ContextOnboardingResponse,
    CountRequest,
    DenseSearchRequest,
    DiscoveryRequest,
    FacetsRequest,
    FilterColumnRequest,
    FilterJsonbPathRequest,
    GraphFirstSearchRequest,
    GroupedSearchRequest,
    JointSearchRequest,
    PointKeysRequest,
    RankFusionSearchRequest,
    RecallCheckRequest,
    TextHybridSearchRequest,
    VectorFirstSearchRequest,
)
from polygres_cli._version import __version__
from polygres_cli.api_openapi import (
    HTTP_METHODS,
    api_route_rows,
    build_api_request_plan,
    inspect_api_operation,
    parse_json_body,
    resolve_api_operation,
)
from polygres_cli.cli_auth import clear_auth, validate_start_response, validated_approved_auth
from polygres_cli.cli_client import CliControlPlaneClient
from polygres_cli.cli_config import (
    DEFAULT_API_BASE_URL,
    ConfigStore,
    access_token,
    env_access_token_set,
    refresh_token,
    resolve_api_base_url,
)
from polygres_cli.cli_errors import (
    CONFLICT,
    GENERAL_FAILURE,
    LOCAL_DEPENDENCY,
    NOT_FOUND,
    SUCCESS,
    UNAVAILABLE,
    USAGE,
    CliError,
    UsageError,
    auth_failure,
    catalog_cli_error,
)
from polygres_cli.cli_notices import display_notices_safely
from polygres_cli.cli_output import print_kv, print_table, write_error, write_json
from polygres_cli.cli_secrets import redact
from polygres_cli.context_inputs import (
    context_deduplicate,
    context_finite_number,
    context_idempotency_key,
    context_model_payload,
    context_parse_jsonb_filters,
    context_read_array,
    context_read_object,
    context_response_model,
    context_validate_embedding,
    context_validate_filter,
    context_validate_identifier,
    context_validate_joint_weights,
    context_validate_recall,
    context_validate_source_keys,
    context_validate_uuid,
    context_validate_weights,
)
from polygres_cli.context_output import (
    context_capabilities_human,
    context_collection_get_human,
    context_collection_status_human,
    context_collections_list_human,
    context_count_human,
    context_deletion_plan_human,
    context_diagnostics_human,
    context_discovery_human,
    context_facets_human,
    context_filters_human,
    context_joint_human,
    context_onboarding_human,
    context_operation_human,
    context_operations_list_human,
    context_point_mutation_human,
    context_point_status_human,
    context_points_scroll_human,
    context_preflight_human,
    context_ranked_human,
    context_recall_human,
    context_verification_human,
    context_wait_progress,
)
from polygres_cli.context_wait import context_wait_for_operation
from polygres_cli.sync_inputs import (
    automatic_sync_selection,
    build_source_connection,
    load_sync_selection,
    sync_idempotency_key,
    sync_stage_idempotency_key,
)

PROJECT_ID_RE = re.compile(r"^p[a-z0-9]{23}$")
PREFLIGHT_ATTEMPT_ID_RE = re.compile(r"^pf[a-z0-9]{22}$")
UUID_LIKE_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MIGRATION_NAME_RE = SQL_IDENTIFIER_RE
GRAPH_CONFIGURATION_KEYS = {
    "registered_tables",
    "registered_relationships",
    "filter_columns",
    "runtime_settings",
}
GRAPH_CONFIGURATION_READ_ONLY_KEYS = {
    "id",
    "project_id",
    "build_status",
    "build_id",
    "last_built_at",
    "needs_rebuild",
    "invalid_reason",
    "created_at",
    "updated_at",
}

# These surfaces expose a database connection or use retired Runtime contracts.
# They must be stopped locally once the control-plane project payload identifies
# a synchronized project, before the CLI resolves a database connection or calls
# a legacy endpoint. The API remains the authoritative enforcement boundary.
SYNCED_PROJECT_UNAVAILABLE_RESOURCES = frozenset({"db", "env"})
SYNCED_PROJECT_CONNECTION_FIELDS = frozenset(
    {
        "database",
        "database_dsn",
        "cnpg_cluster_name",
        "database_name",
        "database_password",
        "database_url",
        "dsn",
        "direct_host",
        "direct_url",
        "direct_url_without_password",
        "password",
        "platform_admin_username",
        "pooled_host",
        "pooled_url",
        "pooled_url_without_password",
        "port",
        "project_owner_username",
        "runtime_namespace",
        "username",
    }
)
SYNCED_PROJECT_CONNECTION_OBJECT_FIELDS = frozenset(
    {
        "connection",
        "connection_info",
        "credentials",
        "direct",
        "pooled",
        "source_connection",
    }
)


class CliArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        code = "INVALID_USAGE" if "invalid choice" in message else "VALIDATION_ERROR"
        raise UsageError(message, code=code)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    argv = _normalize_legacy_project_create_args(argv)
    json_output = "--json" in argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if getattr(args, "version", False):
            sys.stdout.write(f"polygres {__version__}\n")
            _display_post_command_notices(force_refresh=True)
            return SUCCESS
        if not hasattr(args, "func"):
            parser.print_help()
            return SUCCESS
        command_id = str(uuid4())
        command_name = _command_name(args)
        ctx = _context(args, command_id=command_id, command_name=command_name)
        command_started = time.monotonic()
        with ctx.client:
            try:
                _guard_synced_project_surface(ctx, args)
                result = int(args.func(ctx, args))
            except BaseException as exc:
                ctx.client.report_command_completion(
                    command_id=command_id,
                    command_name=command_name,
                    outcome="failed",
                    duration_ms=(time.monotonic() - command_started) * 1000,
                    project_id=_analytics_project_id(ctx),
                    error_code=(
                        exc.code
                        if isinstance(exc, CliError)
                        else "CLI_EXIT_NONZERO"
                        if isinstance(exc, SystemExit)
                        else "UNEXPECTED_CLI_ERROR"
                    ),
                )
                raise
            ctx.client.report_command_completion(
                command_id=command_id,
                command_name=command_name,
                outcome="succeeded" if result == SUCCESS else "failed",
                duration_ms=(time.monotonic() - command_started) * 1000,
                project_id=_analytics_project_id(ctx),
                error_code=None if result == SUCCESS else "CLI_EXIT_NONZERO",
            )
        if result == SUCCESS and args.resource != "notices":
            _display_post_command_notices(base_url=resolve_api_base_url(ctx.config))
        return result
    except SystemExit as exc:
        return int(exc.code or SUCCESS)
    except CliError as exc:
        write_error(exc, json_output=json_output)
        return exc.exit_code


def _normalize_legacy_project_create_args(argv: list[str]) -> list[str]:
    """Keep `projects create NAME` compatible with the typed create namespace."""
    normalized = list(argv)
    for index in range(len(normalized) - 1):
        if normalized[index : index + 2] != ["projects", "create"]:
            continue
        value_index = index + 2
        if value_index >= len(normalized) or normalized[value_index].startswith("-"):
            return normalized
        if normalized[value_index] not in {"standard", "sync"}:
            normalized.insert(value_index, "standard")
        return normalized
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = CliArgumentParser(prog="polygres", description="Polygres command line tool")
    parser.add_argument("--version", action="store_true", help="print the installed CLI version")
    parser.add_argument("--json", action="store_true", help="write machine-readable JSON")
    parser.add_argument("--project", help="project ID or exact project name")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI color output")
    parser.add_argument("--quiet", action="store_true", help="suppress non-essential output")
    parser.add_argument("--verbose", action="store_true", help="print redacted request traces")
    subparsers = parser.add_subparsers(dest="resource", metavar="<resource>")

    _add_auth_parsers(subparsers)
    _add_projects_parsers(subparsers)
    _add_env_parser(subparsers)
    _add_db_parsers(subparsers)
    _add_keys_parsers(subparsers)
    _add_import_parsers(subparsers)
    _add_migration_parsers(subparsers)
    _add_graph_parsers(subparsers)
    _add_vector_parsers(subparsers)
    _add_text_parsers(subparsers)
    _add_ready_parser(subparsers)
    _add_notices_parser(subparsers)
    _add_api_parsers(subparsers)
    _add_context_parsers(subparsers)
    _add_rows_parsers(subparsers)
    _add_config_parsers(subparsers)
    return parser


class Context:
    def __init__(
        self,
        args: argparse.Namespace,
        *,
        command_id: str | None = None,
        command_name: str | None = None,
    ) -> None:
        self.args = args
        self.store = ConfigStore()
        self.config = self.store.load()
        stored_refresh_token = None if env_access_token_set() else refresh_token(self.config)
        self.client = CliControlPlaneClient(
            base_url=resolve_api_base_url(self.config),
            access_token=access_token(self.config),
            refresh_token=stored_refresh_token,
            on_token_refresh=self.store_refreshed_auth,
            on_refresh_auth_failure=self.clear_stored_auth,
            verbose=bool(args.verbose),
            trace=lambda line: sys.stderr.write(line + "\n"),
            command_id=command_id,
            command_name=command_name,
        )
        self._resolved_projects: dict[str, dict[str, Any]] = {}

    @property
    def json(self) -> bool:
        return bool(self.args.json)

    @property
    def quiet(self) -> bool:
        return bool(self.args.quiet)

    @property
    def selected_project_id(self) -> str | None:
        value = self.config.get("selected_project_id")
        return value if isinstance(value, str) else None

    def save(self) -> None:
        self.store.save(self.config)

    def store_refreshed_auth(self, payload: dict[str, Any]) -> None:
        self.config["auth"] = validated_approved_auth(payload)
        self.save()

    def clear_stored_auth(self) -> None:
        clear_auth(self.config)
        self.save()


def _context(
    args: argparse.Namespace,
    *,
    command_id: str | None = None,
    command_name: str | None = None,
) -> Context:
    return Context(args, command_id=command_id, command_name=command_name)


def _command_name(args: argparse.Namespace) -> str:
    parts: list[str] = []
    for name in (
        "resource",
        "action",
        "create_kind",
        "kind",
        "api_action",
        "context_action",
        "rows_action",
        "sources_action",
        "collections_action",
        "filters_action",
        "points_action",
        "operations_action",
        "configs_action",
        "config_action",
    ):
        value = getattr(args, name, None)
        if isinstance(value, str) and value:
            parts.append(value.replace("_", "-"))
    return ".".join(parts)[:80] or "unknown"


def _analytics_project_id(ctx: Context) -> str | None:
    project_id = ctx.args.project or ctx.selected_project_id
    return project_id if project_id is not None and PROJECT_ID_RE.fullmatch(project_id) else None


def _add_auth_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    login = subparsers.add_parser("login", help="sign in through the browser")
    login.add_argument("--timeout", type=_timeout_seconds, default=600)
    login.set_defaults(func=handle_login)
    logout = subparsers.add_parser("logout", help="sign out and remove local credentials")
    logout.set_defaults(func=handle_logout)
    whoami = subparsers.add_parser("whoami", help="show authenticated user")
    whoami.set_defaults(func=handle_whoami)


def _add_projects_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("projects", help="manage projects")
    sub = parser.add_subparsers(dest="action", required=True)
    list_parser = sub.add_parser("list", help="list projects")
    list_parser.set_defaults(func=handle_projects_list)
    use_parser = sub.add_parser("use", help="select a project")
    use_parser.add_argument("project")
    use_parser.set_defaults(func=handle_projects_use)
    create_parser = sub.add_parser("create", help="create a project")
    create_sub = create_parser.add_subparsers(
        dest="create_kind",
        required=True,
        metavar="<project-type>",
    )
    standard = create_sub.add_parser("standard", help="create a managed PostgreSQL project")
    standard.add_argument("name")
    standard.add_argument("--no-wait", action="store_true")
    standard.add_argument("--timeout", type=_timeout_seconds, default=600)
    standard.set_defaults(func=handle_projects_create)
    _add_sync_create_parsers(create_sub)
    status_parser = sub.add_parser("status", help="show project status")
    status_parser.add_argument("status_project", nargs="?", metavar="project")
    status_parser.set_defaults(func=handle_projects_status)


def _add_sync_create_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("sync", help="create a synchronized PostgreSQL project")
    parser.add_argument("name", help="Polygres project name")
    _add_sync_connection_arguments(parser)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--table",
        action="append",
        dest="tables",
        help="table as schema.name (repeatable; schema defaults to public)",
    )
    source.add_argument(
        "--file",
        help="JSON table selection for explicit sync keys or included columns",
    )
    source.add_argument(
        "--all-eligible",
        action="store_true",
        help="synchronize every fully eligible discovered table",
    )
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--timeout", type=_timeout_seconds, default=600)
    parser.add_argument(
        "--idempotency-key",
        help="root key for safely resuming the complete creation workflow",
    )
    parser.set_defaults(func=handle_sync_create)


def _add_sync_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--connection-env",
        metavar="NAME",
        help="environment variable containing the PostgreSQL URL",
    )
    parser.add_argument("--host", help="source PostgreSQL host")
    parser.add_argument("--port", type=int, help="source PostgreSQL port (default: 5432)")
    parser.add_argument("--database", help="source database name")
    parser.add_argument("--username", help="source database username")
    parser.add_argument(
        "--password-env",
        metavar="NAME",
        help="environment variable containing the source password",
    )


def _add_env_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("env", help="print project environment variables")
    parser.set_defaults(func=handle_env)


def _add_db_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("db", help="database commands")
    sub = parser.add_subparsers(dest="action", required=True)
    info = sub.add_parser("info", help="show database connection metadata")
    info.set_defaults(func=handle_db_info)
    psql = sub.add_parser("psql", help="open psql")
    psql.set_defaults(func=handle_db_psql)


def _add_keys_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("keys", help="manage runtime API keys")
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create", help="create an API key")
    create.add_argument("name")
    create.set_defaults(func=handle_keys_create)
    list_parser = sub.add_parser("list", help="list API keys")
    list_parser.set_defaults(func=handle_keys_list)
    revoke = sub.add_parser("revoke", help="revoke an API key")
    revoke.add_argument("key_id")
    revoke.add_argument("--yes", action="store_true")
    revoke.set_defaults(func=handle_keys_revoke)


def _add_import_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("import", help="import data")
    sub = parser.add_subparsers(dest="kind", required=True)
    csv_parser = sub.add_parser("csv", help="import CSV data")
    csv_parser.add_argument("file")
    csv_parser.add_argument("--table", required=True)
    csv_parser.add_argument("--schema", default="public")
    csv_parser.add_argument(
        "--mode",
        choices=["create_table", "append_existing", "replace_existing"],
        default="create_table",
    )
    csv_parser.add_argument("--encoding", choices=["utf-8", "utf-8-sig"], default="utf-8")
    csv_parser.add_argument("--delimiter", type=_delimiter)
    csv_parser.add_argument("--quote-char", type=_one_char)
    csv_parser.add_argument("--escape-char", type=_one_char)
    csv_parser.add_argument("--no-header", action="store_true")
    csv_parser.add_argument("--wait", action="store_true")
    csv_parser.add_argument("--timeout", type=_timeout_seconds, default=1800)
    csv_parser.set_defaults(func=handle_import_csv)
    status = sub.add_parser("status", help="show import status")
    status.add_argument("job_id", nargs="?")
    status.set_defaults(func=handle_import_status)


def _add_migration_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("migrations", help="manage migrations")
    sub = parser.add_subparsers(dest="action", required=True)
    list_parser = sub.add_parser("list", help="list migrations")
    list_parser.set_defaults(func=handle_migrations_list)
    apply = sub.add_parser("apply", help="apply a SQL migration")
    apply.add_argument("--file", required=True)
    apply.add_argument("--name")
    apply.set_defaults(func=handle_migrations_apply)


def _add_graph_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("graph", help="manage graph retrieval")
    sub = parser.add_subparsers(dest="action", required=True)
    discover = sub.add_parser("discover", help="discover graph configuration")
    discover.set_defaults(func=handle_graph_discover)
    config = sub.add_parser("config", help="graph configuration")
    config_sub = config.add_subparsers(dest="config_action", required=True)
    export = config_sub.add_parser("export", help="export graph configuration")
    export.set_defaults(func=handle_graph_config_export)
    apply = config_sub.add_parser("apply", help="apply graph configuration")
    apply.add_argument("--file", required=True)
    apply.set_defaults(func=handle_graph_config_apply)
    build = sub.add_parser("build", help="build graph index")
    build.set_defaults(func=handle_graph_build)
    status = sub.add_parser("status", help="show graph status")
    status.set_defaults(func=handle_graph_status)


def _add_vector_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("vector", help="manage vector retrieval")
    sub = parser.add_subparsers(dest="action", required=True)
    configs = sub.add_parser("configs", help="vector configurations")
    configs_sub = configs.add_subparsers(dest="configs_action", required=True)
    list_parser = configs_sub.add_parser("list", help="list vector configurations")
    list_parser.set_defaults(func=handle_vector_configs_list)
    create = configs_sub.add_parser(
        "create",
        help="retired; create a pgContext collection instead",
    )
    create.add_argument("name", nargs="?")
    create.add_argument("--table")
    create.add_argument("--embedding-column")
    create.add_argument("--dimensions")
    create.add_argument("--schema", default="public")
    create.add_argument("--row-id-column", default="id")
    create.add_argument("--metric")
    create.add_argument("--index-kind")
    create.add_argument("--metadata-column", action="append", default=[])
    create.add_argument("--filter-column", action="append", default=[])
    create.set_defaults(func=handle_vector_configs_create)
    delete = configs_sub.add_parser("delete", help="delete vector configuration")
    delete.add_argument("config_id")
    delete.add_argument("--yes", action="store_true")
    delete.set_defaults(func=handle_vector_configs_delete)
    set_default = configs_sub.add_parser("set-default", help="set the default vector configuration")
    set_default.add_argument("config_id")
    set_default.set_defaults(func=handle_vector_configs_set_default)
    reindex = sub.add_parser("reindex", help="reindex vector configuration")
    reindex.add_argument("config_id")
    reindex.set_defaults(func=handle_vector_reindex)


def _add_text_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("text", help="manage text retrieval")
    sub = parser.add_subparsers(dest="action", required=True)
    configs = sub.add_parser("configs", help="text configurations")
    configs_sub = configs.add_subparsers(dest="configs_action", required=True)
    list_parser = configs_sub.add_parser("list", help="list text configurations")
    list_parser.set_defaults(func=handle_text_configs_list)
    get = configs_sub.add_parser("get", help="show a text configuration")
    get.add_argument("config_id")
    get.set_defaults(func=handle_text_configs_get)
    tsv = configs_sub.add_parser("create-tsvector", help="create TSVector configuration")
    tsv.add_argument("name")
    tsv.add_argument("--table", required=True)
    tsv.add_argument("--tsvector-column")
    tsv.add_argument("--text-column")
    tsv.add_argument("--generated-column")
    tsv.add_argument("--schema", default="public")
    tsv.add_argument("--row-id-column", action="append")
    tsv.add_argument("--language", default="english")
    tsv.add_argument("--default-limit", type=_text_limit, default=10)
    tsv.add_argument("--max-limit", type=_text_limit, default=100)
    tsv.add_argument("--metadata-column", action="append", default=[])
    tsv.add_argument("--filter-column", action="append", default=[])
    tsv.add_argument("--yes", action="store_true")
    tsv.set_defaults(func=handle_text_create_tsvector)
    fuzzy = configs_sub.add_parser("create-fuzzy", help="create fuzzy text configuration")
    fuzzy.add_argument("name")
    fuzzy.add_argument("--table", required=True)
    fuzzy.add_argument("--text-column", required=True)
    fuzzy.add_argument("--schema", default="public")
    fuzzy.add_argument("--row-id-column", action="append")
    fuzzy.add_argument("--language", default="english")
    fuzzy.add_argument("--similarity-threshold", type=_similarity_threshold, default=0.3)
    fuzzy.add_argument("--default-limit", type=_text_limit, default=10)
    fuzzy.add_argument("--max-limit", type=_text_limit, default=100)
    fuzzy.add_argument("--metadata-column", action="append", default=[])
    fuzzy.add_argument("--filter-column", action="append", default=[])
    fuzzy.set_defaults(func=handle_text_create_fuzzy)
    update = configs_sub.add_parser("update", help="update a text configuration")
    update.add_argument("config_id")
    update.add_argument("--table")
    update.add_argument("--schema")
    update.add_argument("--row-id-column", action="append")
    update.add_argument("--text-column")
    update.add_argument("--tsvector-column")
    update.add_argument("--language")
    update.add_argument("--similarity-threshold", type=_similarity_threshold)
    update.add_argument("--default-limit", type=_text_limit)
    update.add_argument("--max-limit", type=_text_limit)
    update.add_argument("--metadata-column", action="append")
    update.add_argument("--filter-column", action="append")
    update.set_defaults(func=handle_text_configs_update)
    diagnostics = configs_sub.add_parser("diagnostics", help="inspect text index health")
    diagnostics.add_argument("config_id")
    diagnostics.set_defaults(func=handle_text_configs_diagnostics)
    reindex = configs_sub.add_parser("reindex", help="rebuild a text index")
    reindex.add_argument("config_id")
    reindex.set_defaults(func=handle_text_configs_reindex)
    delete = configs_sub.add_parser("delete", help="delete text configuration")
    delete.add_argument("config_id")
    delete.add_argument("--yes", action="store_true")
    delete.set_defaults(func=handle_text_configs_delete)


def _add_ready_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("ready", help="show retrieval readiness")
    parser.set_defaults(func=handle_ready)


def _add_notices_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("notices", help="refresh and display active CLI notices")
    parser.set_defaults(func=handle_notices)


def _add_api_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("api", help="inspect and call bundled API routes")
    sub = parser.add_subparsers(dest="api_action", required=True)

    routes = sub.add_parser("routes", help="list routes in the bundled OpenAPI snapshot")
    routes.add_argument("--method", type=str.upper, choices=HTTP_METHODS)
    routes.set_defaults(func=handle_api_routes)

    request = sub.add_parser("request", help="execute a bundled OpenAPI route")
    request.add_argument("route", help="OpenAPI path template or operationId")
    request.add_argument("--method", type=str.upper, choices=HTTP_METHODS)
    request.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="[LOCATION:]NAME=VALUE",
        help="declared path, query, or header parameter; repeat for arrays",
    )
    body = request.add_mutually_exclusive_group()
    body.add_argument("--body", help="inline JSON request body")
    body.add_argument("--body-file", help="UTF-8 JSON file, or - for standard input")
    request.add_argument("--schema", action="store_true", help="inspect route schema only")
    request.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print without calling",
    )
    request.set_defaults(func=handle_api_request)


def _add_context_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("context", help="manage pgContext AI Search")
    sub = parser.add_subparsers(dest="context_action", required=True)

    capabilities = sub.add_parser("capabilities", help="inspect Context capabilities")
    capabilities.set_defaults(func=handle_context_capabilities)

    init = sub.add_parser("init", help="reuse an eligible pgvector embedding column with pgContext")
    init.add_argument("--refresh", action="store_true")
    init.add_argument("--candidate", help="vector configuration UUID")
    init.add_argument("--name", help="Context collection name")
    init.add_argument("--yes", action="store_true")
    _add_context_operation_flags(init)
    init.set_defaults(func=handle_context_init)

    sources = sub.add_parser("sources", help="discover and preflight Context sources")
    sources_sub = sources.add_subparsers(dest="sources_action", required=True)
    discover = sources_sub.add_parser("discover", help="discover Context sources")
    discover.add_argument("--schema", action="append", default=[])
    discover.set_defaults(func=handle_context_sources_discover)
    preflight = sources_sub.add_parser("preflight", help="preflight a collection request")
    preflight.add_argument("--file", required=True)
    preflight.set_defaults(func=handle_context_sources_preflight)

    collections = sub.add_parser("collections", help="manage Context collections")
    collections_sub = collections.add_subparsers(dest="collections_action", required=True)
    list_parser = collections_sub.add_parser("list", help="list Context collections")
    list_parser.add_argument("--status", choices=["ready", "stale", "failed", "deleting"])
    list_parser.add_argument("--limit", type=_context_admin_limit, default=50)
    list_parser.add_argument("--cursor")
    list_parser.set_defaults(func=handle_context_collections_list)
    get = collections_sub.add_parser("get", help="show a Context collection")
    get.add_argument("collection_id")
    get.set_defaults(func=handle_context_collections_get)
    status = collections_sub.add_parser("status", help="show cheap collection status")
    status.add_argument("collection_id")
    status.set_defaults(func=handle_context_collections_status)
    verify = collections_sub.add_parser("verify", help="actively verify a collection")
    verify.add_argument("collection_id")
    verify.set_defaults(func=handle_context_collections_verify)
    create = collections_sub.add_parser("create", help="create a Context collection")
    create.add_argument("name")
    create.add_argument("--file")
    create.add_argument("--source", choices=["existing", "add-column", "new-table"])
    create.add_argument("--schema")
    create.add_argument("--table")
    create.add_argument("--source-key-column")
    create.add_argument("--vector-column")
    create.add_argument("--content-column")
    create.add_argument("--metadata-column")
    create.add_argument("--dimensions", type=_context_dimensions)
    create.add_argument("--metric", choices=["cosine", "inner_product", "l2", "l1"])
    create.add_argument("--text-column")
    create.add_argument("--result-column", action="append", default=[])
    create.add_argument("--filter-column", action="append", default=[])
    create.add_argument("--jsonb-filter", action="append", default=[])
    create.add_argument("--index-kind", choices=["hnsw", "none"])
    create.add_argument("--max-search-limit", type=_context_ranked_limit)
    _add_context_operation_flags(create)
    create.set_defaults(func=handle_context_collections_create)
    update = collections_sub.add_parser("update", help="update collection configuration")
    update.add_argument("collection_id")
    text_group = update.add_mutually_exclusive_group()
    text_group.add_argument("--text-column")
    text_group.add_argument("--clear-text-column", action="store_true")
    update.add_argument("--result-column", action="append", default=[])
    update.add_argument("--clear-result-columns", action="store_true")
    update.add_argument("--max-search-limit", type=_context_ranked_limit)
    _add_context_operation_flags(update)
    update.set_defaults(func=handle_context_collections_update)
    set_default = collections_sub.add_parser(
        "set-default", help="set the default Context collection"
    )
    set_default.add_argument("collection_id")
    _add_context_operation_flags(set_default)
    set_default.set_defaults(func=handle_context_collections_set_default)
    diagnostics = collections_sub.add_parser("diagnostics", help="inspect collection diagnostics")
    diagnostics.add_argument("collection_id")
    diagnostics.set_defaults(func=handle_context_collections_diagnostics)
    reindex = collections_sub.add_parser("reindex", help="rebuild the Context HNSW index")
    reindex.add_argument("collection_id")
    _add_context_operation_flags(reindex)
    reindex.set_defaults(func=handle_context_collections_reindex)
    delete = collections_sub.add_parser("delete", help="delete a Context collection")
    delete.add_argument("collection_id")
    delete.add_argument("--yes", action="store_true")
    _add_context_operation_flags(delete)
    delete.set_defaults(func=handle_context_collections_delete)

    filters = sub.add_parser("filters", help="manage registered Context filters")
    filters_sub = filters.add_subparsers(dest="filters_action", required=True)
    filters_list = filters_sub.add_parser("list", help="list registered filters")
    filters_list.add_argument("collection_id")
    filters_list.set_defaults(func=handle_context_filters_list)
    add_column = filters_sub.add_parser("add-column", help="register a column filter")
    add_column.add_argument("collection_id")
    add_column.add_argument("--key", required=True)
    add_column.add_argument("--column", required=True)
    _add_context_operation_flags(add_column)
    add_column.set_defaults(func=handle_context_filters_add_column)
    add_jsonb = filters_sub.add_parser("add-jsonb-path", help="register a JSONB path filter")
    add_jsonb.add_argument("collection_id")
    add_jsonb.add_argument("--key", required=True)
    add_jsonb.add_argument("--column", required=True)
    add_jsonb.add_argument("--path", action="append", required=True)
    _add_context_operation_flags(add_jsonb)
    add_jsonb.set_defaults(func=handle_context_filters_add_jsonb_path)

    points = sub.add_parser("points", help="manage Context point mappings")
    points_sub = points.add_subparsers(dest="points_action", required=True)
    for action, handler in (
        ("upsert", handle_context_points_upsert),
        ("delete", handle_context_points_delete),
    ):
        command = points_sub.add_parser(action, help=f"{action} Context point mappings")
        command.add_argument("collection_id")
        command.add_argument("source_key", nargs="+")
        _add_context_operation_flags(command)
        command.set_defaults(func=handler)
    point_status = points_sub.add_parser("status", help="show point reconciliation status")
    point_status.add_argument("collection_id")
    point_status.set_defaults(func=handle_context_points_status)
    reconcile = points_sub.add_parser("reconcile", help="fully reconcile Context points")
    reconcile.add_argument("collection_id")
    _add_context_operation_flags(reconcile)
    reconcile.set_defaults(func=handle_context_points_reconcile)
    scroll = points_sub.add_parser("scroll", help="scroll active Context point mappings")
    scroll.add_argument("collection_id")
    scroll.add_argument("--limit", type=_context_admin_limit, default=50)
    scroll.add_argument("--cursor")
    scroll.set_defaults(func=handle_context_points_scroll)

    operations = sub.add_parser("operations", help="inspect durable Context operations")
    operations_sub = operations.add_subparsers(dest="operations_action", required=True)
    operations_list = operations_sub.add_parser("list", help="list Context operations")
    operations_list.add_argument("--collection-id")
    operations_list.add_argument(
        "--kind",
        choices=[
            "collection_create",
            "collection_update",
            "collection_set_default",
            "collection_delete",
            "collection_reindex",
            "filter_add_column",
            "filter_add_jsonb_path",
            "points_upsert",
            "points_delete",
            "points_reconcile",
        ],
    )
    operations_list.add_argument(
        "--status",
        choices=["queued", "running", "cancel_requested", "succeeded", "failed", "cancelled"],
    )
    operations_list.add_argument("--limit", type=_context_admin_limit, default=50)
    operations_list.add_argument("--cursor")
    operations_list.set_defaults(func=handle_context_operations_list)
    operation_get = operations_sub.add_parser("get", help="show a Context operation")
    operation_get.add_argument("operation_id")
    operation_get.set_defaults(func=handle_context_operations_get)
    operation_wait = operations_sub.add_parser("wait", help="wait for a Context operation")
    operation_wait.add_argument("operation_id")
    operation_wait.add_argument("--timeout", type=_timeout_seconds, default=1800)
    operation_wait.add_argument("--poll-interval", type=_context_poll_interval_arg)
    operation_wait.set_defaults(func=handle_context_operations_wait)
    operation_cancel = operations_sub.add_parser("cancel", help="cancel a Context operation")
    operation_cancel.add_argument("operation_id")
    _add_context_operation_flags(operation_cancel)
    operation_cancel.set_defaults(func=handle_context_operations_cancel)
    operation_retry = operations_sub.add_parser("retry", help="retry a Context operation")
    operation_retry.add_argument("operation_id")
    _add_context_operation_flags(operation_retry)
    operation_retry.set_defaults(func=handle_context_operations_retry)

    count = sub.add_parser("count", help="count visible active Context points")
    count.add_argument("collection")
    _add_context_filter_flags(count)
    count.set_defaults(func=handle_context_count)
    facets = sub.add_parser("facets", help="aggregate a registered Context filter")
    facets.add_argument("collection")
    facets.add_argument("field")
    _add_context_filter_flags(facets)
    facets.add_argument("--limit", type=_context_ranked_limit, default=10)
    facets.set_defaults(func=handle_context_facets)

    dense = sub.add_parser("search", help="run dense Context retrieval")
    dense.add_argument("collection")
    _add_context_ranked_flags(dense, filters=True)
    dense.set_defaults(func=handle_context_search)
    text = sub.add_parser("text-hybrid", help="run dense plus text Context retrieval")
    text.add_argument("collection")
    text.add_argument("--query")
    _add_context_ranked_flags(text)
    text.set_defaults(func=handle_context_text_hybrid)
    graph_first = sub.add_parser("graph-first", help="rank a graph neighborhood with Context")
    graph_first.add_argument("collection")
    _add_context_graph_flags(graph_first, start=True, filters=True)
    graph_first.set_defaults(func=handle_context_graph_first)
    vector_first = sub.add_parser("vector-first", help="enrich Context hits with graph evidence")
    vector_first.add_argument("collection")
    _add_context_graph_flags(vector_first, context_limit=True, filters=True)
    vector_first.set_defaults(func=handle_context_vector_first)
    rank_fusion = sub.add_parser("rank-fusion", help="fuse independent Context and graph rankings")
    rank_fusion.add_argument("collection")
    _add_context_graph_flags(
        rank_fusion,
        start=True,
        context_limit=True,
        weights=True,
        filters=True,
    )
    rank_fusion.set_defaults(func=handle_context_rank_fusion)
    joint = sub.add_parser("joint", help="run coupled Context and graph retrieval")
    joint.add_argument("collection")
    _add_context_joint_flags(joint)
    joint.set_defaults(func=handle_context_joint)
    grouped = sub.add_parser("grouped-search", help="group dense Context results")
    grouped.add_argument("collection")
    grouped.add_argument("--group-by")
    grouped.add_argument("--group-limit", type=_context_ranked_limit)
    _add_context_ranked_flags(grouped)
    grouped.set_defaults(func=handle_context_grouped_search)
    recall = sub.add_parser("recall-check", help="compare HNSW results with exact retrieval")
    recall.add_argument("collection")
    recall.add_argument("--minimum-recall", type=_context_finite_float)
    _add_context_ranked_flags(recall, filters=True)
    recall.set_defaults(func=handle_context_recall_check)


def _add_rows_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "rows",
        help="validate and write one table row through the Runtime API",
        description=(
            "Validate or write one JSON object. Use --file - to read the object "
            "once from standard input."
        ),
    )
    sub = parser.add_subparsers(dest="rows_action", required=True)

    validate = sub.add_parser("validate", help="validate a row write without changing data")
    _add_row_common_flags(validate)
    validate.add_argument("--mode", choices=["insert", "upsert", "ignore"], default="insert")
    validate.add_argument("--conflict-column", action="append", default=[])
    validate.add_argument("--update-column", action="append")
    validate.set_defaults(func=handle_rows_validate)

    insert = sub.add_parser("insert", help="insert one row")
    _add_row_common_flags(insert, execution=True)
    insert.set_defaults(func=handle_rows_write, row_mode="insert")

    upsert = sub.add_parser("upsert", help="insert or update one row on a unique conflict")
    _add_row_common_flags(upsert, execution=True)
    upsert.add_argument("--conflict-column", action="append", required=True)
    upsert.add_argument("--update-column", action="append")
    upsert.set_defaults(func=handle_rows_write, row_mode="upsert")

    ignore = sub.add_parser("ignore", help="insert one row or ignore a unique conflict")
    _add_row_common_flags(ignore, execution=True)
    ignore.add_argument("--conflict-column", action="append", required=True)
    ignore.set_defaults(func=handle_rows_write, row_mode="ignore")


def _add_row_common_flags(parser: argparse.ArgumentParser, *, execution: bool = False) -> None:
    parser.add_argument("--schema", default="public")
    parser.add_argument("--table", required=True)
    parser.add_argument(
        "--file",
        required=True,
        help="UTF-8 JSON object file, or - to read standard input once",
    )
    parser.add_argument("--returning", action="append", default=[])
    context = parser.add_mutually_exclusive_group()
    context.add_argument("--context-collection")
    context.add_argument(
        "--reconcile-context",
        action="store_true",
        help="use the only ready Context collection for this table",
    )
    parser.add_argument("--idempotency-key")
    if execution:
        wait = parser.add_mutually_exclusive_group()
        wait.add_argument("--wait", dest="wait", action="store_true", default=True)
        wait.add_argument("--no-wait", dest="wait", action="store_false")
        parser.add_argument("--timeout", type=_timeout_seconds, default=1800)


def _add_context_operation_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--timeout", type=_timeout_seconds, default=1800)
    parser.add_argument("--idempotency-key")


def _add_context_filter_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--filter-json")
    group.add_argument("--filter-file")


def _add_context_ranked_flags(
    parser: argparse.ArgumentParser,
    *,
    filters: bool = False,
) -> None:
    parser.add_argument("--request")
    embedding = parser.add_mutually_exclusive_group()
    embedding.add_argument("--embedding-json")
    embedding.add_argument("--embedding-file")
    parser.add_argument("--limit", type=_context_ranked_limit)
    if filters:
        _add_context_filter_flags(parser)


def _add_context_graph_flags(
    parser: argparse.ArgumentParser,
    *,
    start: bool = False,
    context_limit: bool = False,
    weights: bool = False,
    filters: bool = False,
) -> None:
    if start:
        parser.add_argument("--start-schema")
        parser.add_argument("--start-table")
        parser.add_argument("--start-id")
    if context_limit:
        parser.add_argument("--context-limit", type=_context_ranked_limit)
    parser.add_argument("--max-depth", type=_context_graph_depth)
    parser.add_argument("--graph-limit", type=_context_ranked_limit)
    parser.add_argument("--relationship-type", action="append", default=[])
    parser.add_argument("--direction", choices=["out", "in", "any", "both"])
    if weights:
        parser.add_argument("--context-weight", type=_context_finite_float)
        parser.add_argument("--graph-weight", type=_context_finite_float)
    _add_context_ranked_flags(parser, filters=filters)


def _add_context_joint_flags(parser: argparse.ArgumentParser) -> None:
    _add_context_ranked_flags(parser, filters=True)
    parser.add_argument("--query")
    parser.add_argument("--start-json", action="append", default=[])
    parser.add_argument("--context-limit", type=_context_ranked_limit)
    parser.add_argument("--seed-limit", type=_context_joint_seed_limit)
    parser.add_argument("--max-depth", type=_context_graph_depth)
    parser.add_argument("--graph-limit", type=_context_ranked_limit)
    parser.add_argument("--traversal-limit", type=_context_ranked_limit)
    parser.add_argument("--relationship-type", action="append", default=[])
    parser.add_argument("--direction", choices=["out", "in", "any", "both"])
    parser.add_argument("--semantic-weight", type=_context_finite_float)
    parser.add_argument("--lexical-weight", type=_context_finite_float)
    parser.add_argument("--graph-weight", type=_context_finite_float)


def _add_config_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("config", help="local CLI configuration")
    sub = parser.add_subparsers(dest="action", required=True)
    path = sub.add_parser("path", help="print config path")
    path.set_defaults(func=handle_config_path)


def handle_login(ctx: Context, args: argparse.Namespace) -> int:
    started = ctx.client.start_login({"name": "polygres-cli", "version": __version__})
    session_id, browser_url, poll_token, expires_at, interval = validate_start_response(started)
    opened = False
    try:
        opened = bool(webbrowser.open(browser_url))
    except Exception:  # Browser integrations are platform-specific and fallback is required.
        opened = False
    if not ctx.json and not args.quiet:
        if opened:
            sys.stdout.write("Opened a browser to complete sign-in.\n")
        else:
            sys.stdout.write("Open this URL to complete sign-in:\n")
        sys.stdout.write(f"{browser_url}\n")
        sys.stdout.write(f"Expires: {started['expires_at']}\n")
    elif not opened:
        sys.stderr.write("Open this URL to complete sign-in:\n")
        sys.stderr.write(f"{browser_url}\n")
        sys.stderr.write(f"Expires: {started['expires_at']}\n")

    now = datetime.now(timezone.utc)
    session_seconds = max((expires_at - now).total_seconds(), 0.0)
    deadline = time.monotonic() + min(float(args.timeout), session_seconds)
    status = "pending"
    last_payload: dict[str, Any] = {"status": status}
    while time.monotonic() < deadline:
        _sleep_until_deadline(interval, deadline)
        if time.monotonic() >= deadline:
            break
        last_payload = ctx.client.poll_login(session_id, poll_token, deadline=deadline)
        status = last_payload.get("status")
        if status == "pending":
            interval = _poll_interval(last_payload)
            continue
        if status == "approved":
            auth = validated_approved_auth(last_payload)
            ctx.config["auth"] = auth
            ctx.save()
            ctx.client.adopt_login_credentials(auth)
            output = {"authenticated": True, "user": auth["user"]}
            if ctx.json:
                write_json(output)
            elif not args.quiet:
                user = auth["user"]
                sys.stdout.write(f"Signed in as {user.get('email') or user.get('id') or 'user'}.\n")
            return SUCCESS
        if status == "denied":
            raise auth_failure("CLI_AUTH_DENIED")
        if status == "expired":
            raise auth_failure("CLI_AUTH_EXPIRED")
        raise auth_failure("CLI_AUTH_RESPONSE_INVALID", details={"status": status})
    if expires_at <= datetime.now(timezone.utc):
        raise auth_failure("CLI_AUTH_EXPIRED")
    raise auth_failure("CLI_AUTH_TIMEOUT")


def handle_logout(ctx: Context, args: argparse.Namespace) -> int:
    token = refresh_token(ctx.config)
    if token:
        try:
            ctx.client.revoke_login(token)
        except CliError:
            pass
    clear_auth(ctx.config)
    ctx.save()
    if ctx.json:
        write_json({"logged_out": True})
    elif not args.quiet:
        sys.stdout.write("Logged out.\n")
    return SUCCESS


def handle_whoami(ctx: Context, args: argparse.Namespace) -> int:
    payload = ctx.client.me()
    output = {
        "profile": payload.get("profile") or payload.get("user") or {},
        "organization": payload.get("organization") or {},
        "membership": payload.get("membership") or {},
        "project_count": payload.get("project_count", 0),
        "gate_destination": payload.get("gate_destination"),
        "request_id": payload.get("request_id"),
    }
    organization = output["organization"]
    org_label = ""
    if isinstance(organization, dict):
        org_label = str(organization.get("name") or organization.get("id") or "")
        role = organization.get("role")
        if role:
            org_label = f"{org_label} ({role})" if org_label else str(role)
    return _emit(
        ctx,
        output,
        [("User", output["profile"].get("email", "")), ("Organization", org_label)],
    )


def handle_projects_list(ctx: Context, args: argparse.Namespace) -> int:
    payload = ctx.client.list_projects()
    projects = [_redact_synced_project(project) for project in _items(payload, "projects")]
    output = {
        "projects": projects,
        "selected_project_id": ctx.selected_project_id,
        "request_id": payload.get("request_id"),
    }
    if ctx.json:
        write_json(output)
    elif not ctx.quiet:
        columns = (
            ["external_id", "name", "status"]
            if _has_external_ids(projects)
            else ["id", "name", "status"]
        )
        print_table(output["projects"], columns)
    return SUCCESS


def handle_projects_use(ctx: Context, args: argparse.Namespace) -> int:
    project = _resolve_project(ctx, args.project)
    project_id = _project_api_id(project)
    ctx.config["selected_project_id"] = project_id
    ctx.save()
    output = {
        "project": project,
        "selected_project_id": project_id,
        "request_id": project.get("request_id"),
    }
    if ctx.json:
        write_json(output)
    elif not ctx.quiet:
        sys.stdout.write(f"Selected project: {project.get('name', project_id)} ({project_id})\n")
    return SUCCESS


def handle_projects_create(ctx: Context, args: argparse.Namespace) -> int:
    deadline = time.monotonic() + args.timeout
    payload = ctx.client.create_project(
        args.name, request_timeout=float(args.timeout), deadline=deadline
    )
    project = _redact_synced_project(_object(payload, "project"))
    status = payload.get("status") if isinstance(payload.get("status"), dict) else None
    project_id = _project_api_id(project)
    if not args.no_wait:
        try:
            status = _poll_project_status(ctx, project_id, deadline=deadline)
        except CliError as exc:
            raise _project_create_wait_error(
                project=project,
                project_id=project_id,
                create_request_id=payload.get("request_id"),
                cause=exc,
            ) from exc
    if _is_synced_project(project) and isinstance(status, dict):
        status = _redact_synced_status(status)
    output = {"project": project, "request_id": payload.get("request_id")}
    if status is not None:
        output["status"] = status
    return _emit(
        ctx,
        output,
        [
            ("Project", project.get("external_id") or project.get("id", "")),
            (
                "Status",
                (status.get("project") or status.get("status"))
                if isinstance(status, dict)
                else project.get("status", ""),
            ),
        ],
    )


def handle_projects_status(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, args.status_project)
    payload = ctx.client.get_project_status(project_id)
    output = _project_status_output(project_id, payload)
    return _emit(
        ctx,
        output,
        [
            ("Project", project_id),
            ("Project status", output["project"].get("status", "")),
            ("Runtime status", _summary_value(output["runtime"])),
            ("Resource pressure", _resource_pressure(output["resources"])),
            ("Readiness", _summary_value(output["readiness"])),
        ],
    )


def handle_sync_create(ctx: Context, args: argparse.Namespace) -> int:
    _require_confirmation(
        ctx,
        args.yes,
        "Create a synchronized project? The source database remains authoritative; "
        "direct target mutations and database credentials are unavailable; Polygres manages "
        "the replication publication and slot.",
    )
    connection = _sync_source_connection(ctx, args)
    root_key = sync_idempotency_key(args.idempotency_key)
    deadline = time.monotonic() + args.timeout
    options_payload = ctx.client.project_creation_options()
    options = (
        options_payload.get("options") if isinstance(options_payload.get("options"), dict) else {}
    )
    _require_sync_enabled(options)

    preflight_payload = ctx.client.create_project_preflight(
        connection,
        idempotency_key=sync_stage_idempotency_key(root_key, "source"),
        request_timeout=float(args.timeout),
        deadline=deadline,
    )
    preflight_payload = _poll_sync_preflight(ctx, preflight_payload, deadline=deadline)
    preflight = _sync_preflight(preflight_payload)
    attempt_id = preflight.get("attempt_id")
    if not isinstance(attempt_id, str) or not PREFLIGHT_ATTEMPT_ID_RE.fullmatch(attempt_id):
        raise CliError(
            "SYNC_CREATION_RESPONSE_INVALID",
            "The source inspection did not return a valid internal attempt ID.",
        )
    if preflight.get("status") not in {"source_ready", "admitted"}:
        raise _sync_source_inspection_error(preflight, options, idempotency_key=root_key)

    selection = preflight.get("selection") if isinstance(preflight.get("selection"), dict) else {}
    selected_count = selection.get("selected_count", 0)
    if not isinstance(selected_count, int) or isinstance(selected_count, bool):
        selected_count = 0
    if preflight.get("status") == "source_ready" and selected_count < 1:
        available, _, _ = _list_all_preflight_tables(
            ctx,
            attempt_id,
            cursor=None,
            limit=200,
            all_pages=True,
        )
        selections = _sync_create_selections(ctx, args, available)
        selection_payload = ctx.client.update_project_preflight_selection(
            attempt_id,
            expected_selection_generation=_sync_generation(preflight, "selection_generation"),
            tables=selections,
            idempotency_key=sync_stage_idempotency_key(root_key, "tables"),
        )
        preflight = _sync_preflight(selection_payload)
        selected_count = len(selections)

    _require_sync_create_ready(preflight)
    payload = ctx.client.create_synced_project(
        args.name,
        preflight_attempt_id=attempt_id,
        expected_selection_generation=_sync_generation(preflight, "selection_generation"),
        idempotency_key=sync_stage_idempotency_key(root_key, "project"),
        request_timeout=float(args.timeout),
        deadline=deadline,
    )
    project = _redact_synced_project(_object(payload, "project"))
    project_id = _project_api_id(project)
    status = payload.get("status") if isinstance(payload.get("status"), dict) else None
    if not args.no_wait:
        try:
            status = _poll_project_status(ctx, project_id, deadline=deadline)
        except CliError as exc:
            raise _project_create_wait_error(
                project=project,
                project_id=project_id,
                create_request_id=payload.get("request_id"),
                cause=exc,
            ) from exc
    if isinstance(status, dict):
        status = _redact_synced_status(status)
    output: dict[str, Any] = {
        "project": project,
        "selected_table_count": selected_count,
        "idempotency_key": root_key,
        "request_id": payload.get("request_id"),
    }
    if status is not None:
        output["status"] = status
    return _emit(
        ctx,
        output,
        [
            ("Project", project.get("external_id") or project.get("id", "")),
            (
                "Status",
                (status.get("project") or status.get("status"))
                if isinstance(status, dict)
                else project.get("status", ""),
            ),
            ("Selected tables", selected_count),
            ("Idempotency key", root_key),
        ],
    )


def handle_env(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    conn = ctx.client.connection_info(project_id)
    keys = ctx.client.list_api_keys(project_id)
    output = {
        "env": {
            "DATABASE_URL": _remove_pgbouncer_query(
                conn.get("pooled", {}).get("connection_string_without_password")
            ),
            "DIRECT_URL": _passwordless_url(
                conn.get("direct", {}).get("connection_string_without_password")
            ),
            "POLYGRES_RUNTIME_URL": conn.get("runtime_api_url")
            or conn.get("runtime", {}).get("url"),
        },
        "api_keys": [_sanitize_key(key) for key in _items(keys, "api_keys", "keys")],
        "request_id": conn.get("request_id") or keys.get("request_id"),
    }
    if ctx.json:
        write_json(redact(output))
    elif not ctx.quiet:
        for key, value in output["env"].items():
            if value:
                sys.stdout.write(f"export {key}={shlex.quote(str(value))}\n")
        sys.stdout.write("# POLYGRES_API_KEY is not shown by default. Create one with:\n")
        sys.stdout.write("# polygres keys create <name>\n")
    return SUCCESS


def handle_db_info(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.connection_info(project_id)
    database = _database_output(payload)
    output = {"database": database, "request_id": payload.get("request_id")}
    return _emit(
        ctx,
        output,
        [
            ("Project", database.get("project_id")),
            ("Database", database.get("database")),
            ("Username", database.get("username")),
            ("Port", database.get("port")),
            ("Direct host", database.get("direct_host")),
            ("Pooled host", database.get("pooled_host")),
            ("Ready", database.get("ready")),
        ],
    )


def handle_db_psql(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.connection_info(project_id)
    database = _database_output(payload)
    command = [
        "psql",
        "--host",
        str(database["direct_host"]),
        "--port",
        str(database["port"]),
        "--username",
        str(database["username"]),
        "--dbname",
        str(database["database"]),
    ]
    # Public package boundary: this value is contract-tested against the API's
    # CUSTOMER_CLI registry entry without importing server code into the CLI.
    application_name = "polygres-cli"
    env = {"PGAPPNAME": application_name, "PGSSLMODE": "require"}
    if shutil.which("psql") is None:
        if ctx.json:
            write_json(
                {
                    "command": command,
                    "env": env,
                    "executed": False,
                    "request_id": payload.get("request_id"),
                }
            )
        elif not ctx.quiet:
            sys.stdout.write("psql is not installed or not on PATH.\n\n")
            sys.stdout.write("Run after installing psql:\n")
            sys.stdout.write(
                f"PGAPPNAME={application_name} PGSSLMODE=require " + " ".join(command) + "\n"
            )
        return LOCAL_DEPENDENCY
    if ctx.json:
        write_json(
            {
                "command": command,
                "env": env,
                "executed": True,
                "request_id": payload.get("request_id"),
            }
        )
        return SUCCESS
    child_env = dict(os.environ)
    child_env.pop("PGPASSWORD", None)
    child_env.update(env)
    return subprocess.run(command, env=child_env, check=False).returncode


def handle_keys_list(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.list_api_keys(project_id)
    output = {
        "keys": [_sanitize_key(key) for key in _items(payload, "api_keys", "keys")],
        "request_id": payload.get("request_id"),
    }
    if ctx.json:
        write_json(redact(output))
    elif not ctx.quiet:
        print_table(output["keys"], ["id", "name", "prefix", "status"])
    return SUCCESS


def handle_keys_create(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.create_api_key(project_id, args.name)
    key = _normalize_created_key(payload)
    secret = key.get("secret")
    if not isinstance(secret, str) or not secret:
        raise CliError(
            "API_KEY_RESPONSE_INVALID",
            "API key creation response did not include the one-time secret.",
            request_id=payload.get("request_id"),
        )
    output = {"key": key, "request_id": payload.get("request_id")}
    if ctx.json:
        write_json(output)
    elif not ctx.quiet:
        if sys.stdout.isatty():
            sys.stdout.write("This key is shown once. Store it now.\n\n")
        elif sys.stderr.isatty():
            sys.stderr.write("This key is shown once. Store it now.\n")
        sys.stdout.write(str(key.get("secret", "")) + "\n")
    return SUCCESS


def handle_keys_revoke(ctx: Context, args: argparse.Namespace) -> int:
    _validate_uuid(args.key_id, "key ID")
    project_hint = ctx.args.project or ctx.selected_project_id or "the selected project"
    _require_confirmation(ctx, args.yes, f"Revoke key {args.key_id} for project {project_hint}?")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.revoke_api_key(project_id, args.key_id)
    key = payload.get("key") or payload.get("api_key") or {"id": args.key_id, "status": "revoked"}
    output = {"key": _sanitize_key(key), "revoked": True, "request_id": payload.get("request_id")}
    return _emit(ctx, output, [("Revoked", args.key_id)])


def handle_migrations_list(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.migrations_list(project_id)
    output = {"migrations": _items(payload, "migrations"), "request_id": payload.get("request_id")}
    if ctx.json:
        write_json(output)
    elif not ctx.quiet:
        print_table(output["migrations"], ["id", "name", "version", "status"])
    return SUCCESS


def handle_migrations_apply(ctx: Context, args: argparse.Namespace) -> int:
    sql_path = _readable_file(args.file)
    if args.name:
        _validate_migration_name(args.name)
        name = args.name
    else:
        name = _migration_name(sql_path.stem)
    sql_body = _read_text_file(sql_path)
    project_id = _resolve_project_id(ctx, None)
    created = ctx.client.migrations_create(project_id, name, sql_body)
    migration = _object(created, "migration")
    migration_id = migration.get("id")
    _validate_response_uuid(migration_id, "migration")
    applied = ctx.client.migrations_apply(project_id, migration_id)
    applied_migration = applied.get("migration", migration)
    create_operation = (
        created.get("operation") if isinstance(created.get("operation"), dict) else {}
    )
    apply_operation = applied.get("operation") if isinstance(applied.get("operation"), dict) else {}
    status = applied_migration.get("status")
    output = {
        "migration": applied_migration,
        "operation": {
            "created": bool(create_operation.get("created", True)),
            "applied": bool(apply_operation.get("applied", status == "applied")),
            "noop": bool(create_operation.get("noop") or apply_operation.get("noop")),
        },
        "request_id": applied.get("request_id") or created.get("request_id"),
    }
    _emit(
        ctx,
        output,
        [
            ("Migration", output["migration"].get("name", name)),
            ("Status", output["migration"].get("status", "")),
        ],
    )
    return GENERAL_FAILURE if status == "failed" else SUCCESS


def handle_graph_discover(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    response = ctx.client.graph_discover(project_id)
    return _emit_configuration(
        ctx,
        {
            "configuration": _graph_discovery_configuration(response),
            "request_id": response.get("request_id"),
        },
    )


def handle_graph_config_export(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    return _emit_configuration(ctx, ctx.client.get_graph_configuration(project_id))


def handle_graph_config_apply(ctx: Context, args: argparse.Namespace) -> int:
    payload = _graph_configuration_file(args.file)
    project_id = _resolve_project_id(ctx, None)
    response = ctx.client.put_graph_configuration(project_id, payload)
    return _emit_configuration(
        ctx,
        response,
        operation=response.get("operation", {"applied": True}),
    )


def handle_graph_build(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.graph_build(project_id)
    operation = payload.get("operation")
    build_status = payload.get("build_status") or payload.get("configuration", {}).get(
        "build_status"
    )
    if not isinstance(operation, dict):
        operation = {
            "build_started": True,
            "build_completed": build_status == "ready",
        }
    output = {
        "graph": payload.get("graph", payload.get("configuration", {})),
        "operation": operation,
        "request_id": payload.get("request_id"),
    }
    return _emit(ctx, output, [("Graph", output["graph"].get("build_status", ""))])


def handle_graph_status(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.graph_status(project_id)
    graph = payload.get("graph") or payload.get("status") or {}
    human_items: list[tuple[str, Any]] = [("Graph", graph.get("build_status", ""))]
    reason = graph.get("invalid_reason") or graph.get("reason")
    if reason:
        human_items.append(("Reason", str(reason)[:160]))
    difference_summary = _graph_difference_summary(graph.get("differences"))
    if difference_summary:
        human_items.append(("Differences", difference_summary))
    return _emit(
        ctx,
        {"graph": graph, "request_id": payload.get("request_id")},
        human_items,
    )


def handle_vector_configs_list(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.list_vector_configurations(project_id)
    output = {
        "configurations": _items(payload, "configurations", "vector_configurations"),
        "request_id": payload.get("request_id"),
    }
    if ctx.json:
        write_json(output)
    elif not ctx.quiet:
        print_table(
            output["configurations"],
            [
                "id",
                "name",
                "is_default",
                "index_status",
                "index_error",
                "dimensions",
                "metric",
            ],
        )
    return SUCCESS


def handle_vector_configs_create(ctx: Context, args: argparse.Namespace) -> int:
    raise CliError(
        "VECTOR_CREATION_RETIRED",
        "New pgvector column registrations are no longer supported.\n"
        "Update your CLI version with `pipx upgrade polygres-cli`, and create a collection "
        "using `polygres context collections create`.\n"
        "Refer to the documentation for more information: "
        "https://docs.evokoa.com/polygres/cli/context#collection-lifecycle",
        exit_code=USAGE,
        details={
            "replacement": "pgcontext_collection",
            "command": "polygres context collections create",
            "upgrade_command": "pipx upgrade polygres-cli",
            "documentation_url": (
                "https://docs.evokoa.com/polygres/cli/context#collection-lifecycle"
            ),
        },
    )


def handle_vector_configs_delete(ctx: Context, args: argparse.Namespace) -> int:
    _validate_uuid(args.config_id, "configuration ID")
    _require_confirmation(ctx, args.yes, f"Delete vector configuration {args.config_id}?")
    project_id = _resolve_project_id(ctx, None)
    response = ctx.client.delete_vector_configuration(project_id, args.config_id)
    return _emit_config_response(ctx, response, default_operation={"deleted": True})


def handle_vector_configs_set_default(ctx: Context, args: argparse.Namespace) -> int:
    _validate_uuid(args.config_id, "configuration ID")
    project_id = _resolve_project_id(ctx, None)
    response = ctx.client.set_default_vector_configuration(project_id, args.config_id)
    return _emit_config_response(ctx, response, default_operation={"default_set": True})


def handle_vector_reindex(ctx: Context, args: argparse.Namespace) -> int:
    _validate_uuid(args.config_id, "configuration ID")
    project_id = _resolve_project_id(ctx, None)
    response = ctx.client.reindex_vector_configuration(project_id, args.config_id)
    return _emit_config_response(ctx, response, default_operation={"reindexed": True})


def handle_text_configs_list(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.list_text_configurations(project_id)
    output = {
        "configurations": _items(payload, "configurations", "text_configurations"),
        "request_id": payload.get("request_id"),
    }
    if ctx.json:
        write_json(output)
    elif not ctx.quiet:
        print_table(output["configurations"], ["id", "name", "search_kind", "index_status"])
    return SUCCESS


def handle_text_configs_get(ctx: Context, args: argparse.Namespace) -> int:
    _validate_text_config_ref(args.config_id)
    project_id = _resolve_project_id(ctx, None)
    return _emit_config_response(ctx, ctx.client.get_text_configuration(project_id, args.config_id))


def handle_text_create_tsvector(ctx: Context, args: argparse.Namespace) -> int:
    row_id_columns = args.row_id_column or ["id"]
    _validate_text_limits(args.default_limit, args.max_limit)
    generated_mode = bool(args.text_column or args.generated_column)
    existing_mode = bool(args.tsvector_column)
    if existing_mode == generated_mode:
        raise CliError(
            "VALIDATION_ERROR",
            "Provide exactly one of --tsvector-column or --text-column with --generated-column.",
            exit_code=USAGE,
        )
    _validate_identifiers(args.schema, args.table, *row_id_columns, args.language)
    _validate_identifiers(*args.metadata_column, *args.filter_column)
    if existing_mode:
        _validate_identifiers(args.tsvector_column)
        generated_column_created = False
        tsvector_setup: dict[str, Any] = {
            "mode": "existing",
            "column": args.tsvector_column,
            "language": args.language,
        }
    else:
        if not args.text_column or not args.generated_column:
            raise CliError(
                "VALIDATION_ERROR",
                "Generated-column mode requires --text-column and --generated-column.",
                exit_code=USAGE,
            )
        _require_confirmation(ctx, args.yes, "Create a generated tsvector column?")
        _validate_identifiers(args.text_column, args.generated_column)
        generated_column_created = True
        tsvector_setup = {
            "mode": "generate",
            "source_columns": [args.text_column],
            "generated_column": args.generated_column,
            "language": args.language,
        }
    project_id = _resolve_project_id(ctx, None)
    payload = {
        "name": args.name,
        "search_kind": "tsvector",
        "schema_name": args.schema,
        "table_name": args.table,
        "row_id_column": row_id_columns[0],
        "row_id_columns": row_id_columns,
        "language": args.language,
        "default_limit": args.default_limit,
        "max_limit": args.max_limit,
        "metadata_columns": args.metadata_column,
        "filter_columns": args.filter_column,
    }
    payload["tsvector"] = tsvector_setup
    response = ctx.client.create_text_configuration(project_id, payload)
    output = {
        "configuration": response.get("configuration", {}),
        "operation": {
            **(response.get("operation") if isinstance(response.get("operation"), dict) else {}),
            "generated_column_created": generated_column_created,
        },
        "request_id": response.get("request_id"),
    }
    return _emit(ctx, output, [("Configuration", output["configuration"].get("id", ""))])


def handle_text_create_fuzzy(ctx: Context, args: argparse.Namespace) -> int:
    row_id_columns = args.row_id_column or ["id"]
    _validate_text_limits(args.default_limit, args.max_limit)
    _validate_identifiers(args.schema, args.table, *row_id_columns, args.text_column, args.language)
    _validate_identifiers(*args.metadata_column, *args.filter_column)
    payload = {
        "name": args.name,
        "search_kind": "fuzzy",
        "schema_name": args.schema,
        "table_name": args.table,
        "row_id_column": row_id_columns[0],
        "row_id_columns": row_id_columns,
        "text_column": args.text_column,
        "language": args.language,
        "default_limit": args.default_limit,
        "max_limit": args.max_limit,
        "metadata_columns": args.metadata_column,
        "filter_columns": args.filter_column,
        "similarity_threshold": args.similarity_threshold,
    }
    project_id = _resolve_project_id(ctx, None)
    response = ctx.client.create_text_configuration(project_id, payload)
    return _emit_config_response(ctx, response)


def handle_text_configs_delete(ctx: Context, args: argparse.Namespace) -> int:
    _validate_text_config_ref(args.config_id)
    _require_confirmation(ctx, args.yes, f"Delete text configuration {args.config_id}?")
    project_id = _resolve_project_id(ctx, None)
    response = ctx.client.delete_text_configuration(project_id, args.config_id)
    return _emit_config_response(ctx, response, default_operation={"deleted": True})


def handle_text_configs_update(ctx: Context, args: argparse.Namespace) -> int:
    _validate_text_config_ref(args.config_id)
    if args.default_limit is not None and args.max_limit is not None:
        _validate_text_limits(args.default_limit, args.max_limit)
    identifiers = [
        value
        for value in (
            args.schema,
            args.table,
            args.text_column,
            args.tsvector_column,
            args.language,
            *(args.row_id_column or []),
            *(args.metadata_column or []),
            *(args.filter_column or []),
        )
        if value is not None
    ]
    _validate_identifiers(*identifiers)
    payload = {
        key: value
        for key, value in {
            "schema_name": args.schema,
            "table_name": args.table,
            "row_id_columns": args.row_id_column,
            "text_column": args.text_column,
            "tsvector_column": args.tsvector_column,
            "language": args.language,
            "similarity_threshold": args.similarity_threshold,
            "default_limit": args.default_limit,
            "max_limit": args.max_limit,
            "metadata_columns": args.metadata_column,
            "filter_columns": args.filter_column,
        }.items()
        if value is not None
    }
    if not payload:
        raise CliError("VALIDATION_ERROR", "Provide at least one field to update.", exit_code=USAGE)
    project_id = _resolve_project_id(ctx, None)
    return _emit_config_response(
        ctx, ctx.client.update_text_configuration(project_id, args.config_id, payload)
    )


def handle_text_configs_diagnostics(ctx: Context, args: argparse.Namespace) -> int:
    _validate_text_config_ref(args.config_id)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.diagnose_text_configuration(project_id, args.config_id)
    return _emit(
        ctx,
        payload,
        [
            ("Configuration", payload.get("configuration", {}).get("name", "")),
            ("Healthy", payload.get("diagnostics", {}).get("healthy", False)),
            ("Index found", payload.get("diagnostics", {}).get("index_found", False)),
            ("Index valid", payload.get("diagnostics", {}).get("index_valid", False)),
        ],
    )


def handle_text_configs_reindex(ctx: Context, args: argparse.Namespace) -> int:
    _validate_text_config_ref(args.config_id)
    project_id = _resolve_project_id(ctx, None)
    return _emit_config_response(
        ctx,
        ctx.client.reindex_text_configuration(project_id, args.config_id),
        default_operation={"reindexed": True},
    )


def handle_import_csv(ctx: Context, args: argparse.Namespace) -> int:
    file_path = _readable_file(args.file)
    _validate_identifiers(args.schema, args.table)
    preview_fields = {
        "target_schema": args.schema,
        "target_table": args.table,
        "mode": args.mode,
        "encoding": args.encoding,
        "has_header": "false" if args.no_header else "true",
        "sample_row_count": "50",
    }
    for cli_name, field_name in [
        ("delimiter", "delimiter"),
        ("quote_char", "quote_char"),
        ("escape_char", "escape_char"),
    ]:
        value = getattr(args, cli_name)
        if value is not None:
            preview_fields[field_name] = value
    project_id = _resolve_project_id(ctx, None)
    preview = ctx.client.csv_preview(project_id, file_path, preview_fields)
    preview_payload = preview.get("preview") if isinstance(preview.get("preview"), dict) else {}
    job_id = preview_payload.get("job_id")
    if not isinstance(job_id, str):
        raise CliError(
            "IMPORT_INVALID",
            "The API returned an incomplete CSV preview. Retry the import. "
            "If it happens again, contact support.",
            request_id=(str(preview.get("request_id")) if preview.get("request_id") else None),
        )
    _validate_response_uuid(job_id, "import preview job")
    columns = preview_payload.get("columns")
    if not isinstance(columns, list):
        raise CliError(
            "IMPORT_INVALID",
            "The API returned an incomplete CSV preview. Retry the import. "
            "If it happens again, contact support.",
            request_id=(str(preview.get("request_id")) if preview.get("request_id") else None),
        )
    import_fields: dict[str, object] = {
        "target_schema": args.schema,
        "target_table": args.table,
        "mode": args.mode,
        "encoding": str(preview_payload.get("encoding", args.encoding)),
        "delimiter": str(preview_payload.get("delimiter", args.delimiter or "")),
        "quote_char": str(preview_payload.get("quote_char", args.quote_char or '"')),
        "has_header": bool(preview_payload.get("has_header", not args.no_header)),
    }
    effective_escape = preview_payload.get("escape_char", args.escape_char)
    if effective_escape is not None:
        import_fields["escape_char"] = str(effective_escape)
    import_fields.update({"job_id": job_id, "columns": columns})
    started = ctx.client.start_csv_import(project_id, import_fields)
    output = _import_output(started)
    if args.wait and output["import"].get("status") not in {"succeeded", "failed", "cancelled"}:
        import_id = output["import"].get("id")
        _validate_response_uuid(import_id, "import job")
        output = _poll_import(ctx, project_id, import_id, args.timeout, started)
    if ctx.json:
        write_json(output)
    elif not ctx.quiet:
        _write_import_human(output)
    return _import_exit_code(output["import"])


def handle_import_status(ctx: Context, args: argparse.Namespace) -> int:
    if args.job_id:
        _validate_uuid(args.job_id, "import job ID")
    project_id = _resolve_project_id(ctx, None)
    if args.job_id:
        job_id = args.job_id
    else:
        imports_payload = ctx.client.list_imports(project_id)
        imports = _items(imports_payload, "imports")
        job_id = _latest_import_id(imports)
        if job_id is None:
            output = {
                "imports": imports,
                "latest_import": None,
                "request_id": imports_payload.get("request_id"),
            }
            if ctx.json:
                write_json(output)
            elif not ctx.quiet:
                sys.stdout.write("No imports found.\n")
                if output.get("request_id"):
                    sys.stdout.write(f"Request ID: {output['request_id']}\n")
            return SUCCESS
    _validate_uuid(job_id, "import job ID")
    output = _import_output(ctx.client.get_import(project_id, job_id))
    if ctx.json:
        write_json(output)
    elif not ctx.quiet:
        _write_import_human(output)
    return _import_exit_code(output["import"])


def handle_ready(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.retrieval_readiness(project_id)
    output = {
        "project_id": payload.get("project_id", project_id),
        "graph": payload.get("graph", {}),
        "vector": payload.get("vector", {}),
        "hybrid": payload.get("hybrid", {}),
        "request_id": payload.get("request_id"),
    }
    return _emit(
        ctx,
        output,
        [
            ("Project", output["project_id"]),
            ("Graph ready", output["graph"].get("ready", "")),
            ("Vector ready", output["vector"].get("ready", "")),
            ("Hybrid ready", output["hybrid"].get("ready", "")),
        ],
    )


def handle_api_routes(ctx: Context, args: argparse.Namespace) -> int:
    rows = api_route_rows(method=args.method)
    if ctx.json:
        write_json({"routes": rows})
    elif not ctx.quiet:
        print_table(rows, ["method", "route", "operation_id", "summary"])
    return SUCCESS


def handle_api_request(ctx: Context, args: argparse.Namespace) -> int:
    operation = resolve_api_operation(args.route, method=args.method)
    if args.schema:
        if args.param or args.body is not None or args.body_file is not None or args.dry_run:
            raise UsageError(
                "--schema cannot be combined with request parameters, a body, or --dry-run.",
                code="INVALID_USAGE",
            )
        return _emit_api_payload(ctx, inspect_api_operation(operation))

    body, body_provided = _api_request_body(args)
    default_project_id: str | None = None
    has_explicit_project_parameter = any(
        raw.split("=", 1)[0] in {"project_id", "path:project_id"}
        for raw in args.param
        if "=" in raw
    )
    route_uses_project = any(
        parameter.get("in") == "path" and parameter.get("name") == "project_id"
        for parameter in inspect_api_operation(operation)["parameters"]
    )
    if route_uses_project and not has_explicit_project_parameter:
        if args.project and PROJECT_ID_RE.fullmatch(args.project):
            default_project_id = args.project
        elif ctx.selected_project_id:
            default_project_id = ctx.selected_project_id
        elif not args.dry_run:
            default_project_id = _resolve_project_id(ctx, None)
        elif args.project:
            raise UsageError(
                "--dry-run cannot resolve a project name. Pass a project ID with "
                "--project or --param path:project_id=...",
                code="API_PARAMETER_REQUIRED",
            )

    plan = build_api_request_plan(
        operation,
        args.param,
        body=body,
        body_provided=body_provided,
        default_project_id=default_project_id,
    )
    if args.dry_run:
        return _emit_api_payload(ctx, {"dry_run": True, "request": plan.output()})
    return _emit_api_payload(ctx, ctx.client.api_request(plan))


def _api_request_body(args: argparse.Namespace) -> tuple[Any, bool]:
    if args.body is not None:
        return parse_json_body(args.body, source="--body"), True
    if args.body_file is None:
        return None, False
    if args.body_file == "-":
        try:
            raw = sys.stdin.read()
        except OSError as exc:
            raise UsageError(
                "Could not read the JSON request body from standard input.",
                code="API_BODY_INVALID",
            ) from exc
        return parse_json_body(raw, source="standard input"), True
    path = _readable_file(args.body_file)
    return parse_json_body(_read_text_file(path), source=str(path)), True


def _emit_api_payload(ctx: Context, payload: Any) -> int:
    if ctx.json:
        write_json(payload)
    elif not ctx.quiet:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return SUCCESS


def handle_context_capabilities(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_capabilities(project_id)
    return _context_emit(ctx, payload, context_capabilities_human)


def handle_rows_validate(ctx: Context, args: argparse.Namespace) -> int:
    request = _row_request(args, mode=args.mode, execution=False)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.rows_validate(
        project_id,
        args.schema,
        args.table,
        request,
    )
    return _emit_row_result(
        ctx,
        payload,
        requested_returning=request.get("returning"),
    )


def handle_rows_write(ctx: Context, args: argparse.Namespace) -> int:
    request = _row_request(args, mode=args.row_mode, execution=True)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.rows_write(
        project_id,
        args.schema,
        args.table,
        request,
    )
    context_result = payload.get("context")
    if (
        args.wait
        and payload.get("status") == "pending"
        and isinstance(context_result, dict)
        and context_result.get("operation_id")
    ):
        operation_id = str(context_result["operation_id"])
        try:
            context_wait_for_operation(
                ctx.client,
                project_id=project_id,
                operation_id=operation_id,
                timeout_seconds=args.timeout,
                initial_envelope=None,
            )
        except CliError as exc:
            if exc.code == "CONTEXT_OPERATION_TIMEOUT":
                return _emit_row_result(
                    ctx,
                    payload,
                    requested_returning=request.get("returning"),
                )
            operation_status = exc.details.get("operation_status")
            if operation_status not in {"failed", "cancelled"}:
                exc.details.setdefault("operation_id", operation_id)
                key = request.get("idempotency_key")
                if isinstance(key, str):
                    exc.details.setdefault("idempotency_key", key)
                raise
            payload["status"] = "partial_failed"
            context_result["status"] = "partial_failed"
            context_result["operation_status"] = operation_status
            context_result["error"] = {
                "code": "ROW_CONTEXT_RECONCILIATION_FAILED",
                "message": "The row committed, but Context reconciliation failed.",
                "retryable": bool(exc.details.get("retryable", False)),
                "details": {
                    "operation_id": operation_id,
                    "underlying_code": exc.code,
                },
            }
        else:
            payload = ctx.client.rows_write(
                project_id,
                args.schema,
                args.table,
                request,
            )
    return _emit_row_result(
        ctx,
        payload,
        exit_code=UNAVAILABLE if payload.get("status") == "partial_failed" else SUCCESS,
        requested_returning=request.get("returning"),
    )


def _row_request(
    args: argparse.Namespace,
    *,
    mode: str,
    execution: bool,
) -> dict[str, Any]:
    for value in (args.schema, args.table):
        if len(value) > 63 or SQL_IDENTIFIER_RE.fullmatch(value) is None:
            raise CliError(
                "ROW_REQUEST_INVALID",
                "Schema and table names must be portable PostgreSQL identifiers.",
                exit_code=USAGE,
                details={"field": "identifier"},
            )
    row = context_read_object(
        args.file,
        file_input=True,
        code="ROW_REQUEST_INVALID",
        allow_stdin=True,
    )
    if not row:
        raise CliError(
            "ROW_REQUEST_INVALID",
            "The row JSON object must not be empty.",
            exit_code=USAGE,
            details={"field": "row"},
        )
    conflict_columns = _row_columns(getattr(args, "conflict_column", []), "conflict_column")
    update_value = getattr(args, "update_column", None)
    update_columns = (
        _row_columns(update_value, "update_column") if update_value is not None else None
    )
    returning = _row_columns(args.returning, "returning")
    for column in row:
        _row_identifier(column, "row")
    if mode == "insert" and (conflict_columns or update_columns is not None):
        raise CliError(
            "ROW_OPTION_INVALID",
            "Insert does not accept conflict or update columns.",
            exit_code=USAGE,
            details={"mode": mode},
        )
    if mode in {"upsert", "ignore"} and not conflict_columns:
        raise CliError(
            "ROW_CONFLICT_CONSTRAINT_INVALID",
            "Upsert and ignore require at least one --conflict-column.",
            exit_code=USAGE,
        )
    if mode == "ignore" and update_columns is not None:
        raise CliError(
            "ROW_OPTION_INVALID",
            "Ignore does not accept update columns.",
            exit_code=USAGE,
            details={"mode": mode},
        )
    requested_context = bool(args.context_collection or args.reconcile_context)
    if args.context_collection and UUID_LIKE_RE.fullmatch(args.context_collection) is None:
        raise CliError(
            "CONTEXT_COLLECTION_NOT_FOUND",
            "--context-collection must be a UUID.",
            exit_code=USAGE,
        )
    if args.idempotency_key and not requested_context:
        raise CliError(
            "ROW_OPTION_INVALID",
            "--idempotency-key requires Context reconciliation.",
            exit_code=USAGE,
            details={"mode": mode},
        )
    body: dict[str, Any] = {
        "mode": mode,
        "row": row,
        "returning": returning,
    }
    if conflict_columns:
        body["conflict_columns"] = conflict_columns
    if update_columns is not None:
        body["update_columns"] = update_columns
    if requested_context:
        body["context"] = {
            "reconcile": True,
            **({"collection_id": args.context_collection} if args.context_collection else {}),
        }
        if execution:
            body["idempotency_key"] = args.idempotency_key or f"rows-{uuid4()}"
    return body


def _row_columns(values: list[str] | None, field: str) -> list[str]:
    result = list(values or [])
    if len(result) != len(set(result)):
        raise CliError(
            "ROW_REQUEST_INVALID",
            f"Duplicate --{field.replace('_', '-')} values are not allowed.",
            exit_code=USAGE,
            details={"field": field},
        )
    for value in result:
        _row_identifier(value, field)
    return result


def _row_identifier(value: str, field: str) -> None:
    if len(value) > 63 or SQL_IDENTIFIER_RE.fullmatch(value) is None:
        raise CliError(
            "ROW_REQUEST_INVALID",
            "Row column names must be portable PostgreSQL identifiers.",
            exit_code=USAGE,
            details={"field": field},
        )


def _emit_row_result(
    ctx: Context,
    payload: dict[str, Any],
    *,
    exit_code: int = SUCCESS,
    requested_returning: Any = None,
) -> int:
    if ctx.json:
        write_json(redact(payload))
        return exit_code
    if not ctx.quiet:
        context_result = payload.get("context")
        returned_keys = (
            [str(value) for value in requested_returning]
            if isinstance(requested_returning, list)
            else list(payload.get("returned") or {})
        )
        items = [
            ("operation", payload.get("operation", "validated")),
            ("table", f"{payload.get('schema')}.{payload.get('table')}"),
            (
                "returned keys",
                ", ".join(returned_keys) if returned_keys else "none",
            ),
            ("status", payload.get("status", "valid")),
        ]
        if isinstance(context_result, dict):
            items.extend(
                [
                    ("context", context_result.get("status")),
                    ("operation id", context_result.get("operation_id") or "none"),
                ]
            )
        if payload.get("idempotency_key"):
            items.append(("idempotency key", payload["idempotency_key"]))
        if payload.get("request_id"):
            items.append(("request id", payload["request_id"]))
        print_kv(items)
    if exit_code != SUCCESS:
        sys.stderr.write(
            "The row committed, but Context reconciliation did not complete. "
            "Resume the same row operation with the displayed idempotency key.\n"
        )
    return exit_code


def handle_context_init(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    action = "refresh" if args.refresh else "evaluate"
    payload = ctx.client.context_onboarding_action(project_id, action)
    onboarding = context_response_model(ContextOnboardingResponse, payload)
    status_value = (
        onboarding.status.value if hasattr(onboarding.status, "value") else onboarding.status
    )
    status = str(status_value)
    if status in {"completed", "dismissed", "ineligible"}:
        return _context_emit(ctx, payload, context_onboarding_human)

    candidates = [candidate.model_dump(mode="json") for candidate in onboarding.candidates]
    if not candidates:
        return _context_emit(ctx, payload, context_onboarding_human)
    selected = _context_onboarding_candidate(candidates, args.candidate)
    ctx.client.context_onboarding_action(project_id, "acknowledge")

    if not args.yes:
        if ctx.json or not sys.stdin.isatty():
            return _context_emit(ctx, payload, context_onboarding_human)
        sys.stderr.write(
            "Reuse "
            f"{selected['schema_name']}.{selected['table_name']}."
            f"{selected['embedding_column']} for pgContext? [y/N] "
        )
        if sys.stdin.readline().strip().lower() not in {"y", "yes"}:
            dismissed = ctx.client.context_onboarding_action(project_id, "dismiss")
            return _context_emit(ctx, dismissed, context_onboarding_human)

    collection_name = args.name or f"{selected['table_name']}_context"[:63]
    context_validate_identifier(collection_name, field="name")
    request = context_model_payload(
        CollectionCreateRequest,
        {
            "name": collection_name,
            "source": {
                "mode": "existing",
                "schema_name": selected["schema_name"],
                "table_name": selected["table_name"],
                "source_key_column": selected["row_id_column"],
            },
            "vector": {
                "column_name": selected["embedding_column"],
                "dimensions": selected["dimensions"],
                "metric": selected["metric"],
            },
            "index_kind": "hnsw",
        },
    )
    key = context_idempotency_key(args.idempotency_key)
    operation = ctx.client.context_collections_create(
        project_id,
        request,
        idempotency_key=key,
    )
    return _context_mutation_result(ctx, args, project_id, operation, key)


def _context_onboarding_candidate(
    candidates: list[dict[str, Any]], candidate_id: str | None
) -> dict[str, Any]:
    if candidate_id is not None:
        context_validate_uuid(candidate_id, field="candidate")
        matches = [
            item for item in candidates if str(item["vector_configuration_id"]) == candidate_id
        ]
        if matches:
            return matches[0]
        raise CliError(
            "CONTEXT_ONBOARDING_NOT_ELIGIBLE",
            "The selected vector configuration is not an eligible bridge candidate.",
            exit_code=CONFLICT,
        )
    if len(candidates) == 1:
        return candidates[0]
    raise CliError(
        "CONTEXT_ONBOARDING_CANDIDATE_REQUIRED",
        "Multiple eligible vector configurations were found. Pass --candidate <uuid>.",
        exit_code=USAGE,
    )


def handle_context_sources_discover(ctx: Context, args: argparse.Namespace) -> int:
    schemas = context_deduplicate(args.schema)
    for index, schema in enumerate(schemas):
        context_validate_identifier(schema, field=f"schema_names.{index}")
    request = context_model_payload(
        DiscoveryRequest,
        {"schema_names": schemas} if schemas else {},
        exclude_unset=True,
    )
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_discover(project_id, request)
    return _context_emit(ctx, payload, context_discovery_human)


def handle_context_sources_preflight(ctx: Context, args: argparse.Namespace) -> int:
    request = context_read_object(args.file, file_input=True, allow_stdin=True)
    request = context_model_payload(CollectionCreateRequest, request)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_preflight(project_id, request)
    return _context_emit(
        ctx,
        payload,
        context_preflight_human,
        quiet=ctx.quiet,
    )


def handle_context_collections_list(ctx: Context, args: argparse.Namespace) -> int:
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_collections_list(
        project_id,
        status=args.status,
        limit=args.limit,
        cursor=args.cursor,
    )
    return _context_emit(ctx, payload, context_collections_list_human)


def handle_context_collections_get(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_collections_get(project_id, args.collection_id)
    return _context_emit(ctx, payload, context_collection_get_human)


def handle_context_collections_status(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_collections_status(project_id, args.collection_id)
    return _context_emit(ctx, payload, context_collection_status_human)


def handle_context_collections_verify(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_collections_verify(project_id, args.collection_id)
    return _context_emit(ctx, payload, context_verification_human)


def handle_context_collections_create(ctx: Context, args: argparse.Namespace) -> int:
    request = _context_collection_create_request(args)
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_collections_create(
        project_id,
        request,
        idempotency_key=key,
    )
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_collections_update(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    if args.clear_result_columns and args.result_column:
        raise CliError(
            "CONTEXT_REQUEST_INVALID",
            "--clear-result-columns cannot be combined with --result-column.",
            exit_code=USAGE,
        )
    request: dict[str, Any] = {}
    if args.clear_text_column:
        request["text_column"] = None
    elif args.text_column is not None:
        request["text_column"] = args.text_column
    if args.clear_result_columns:
        request["result_columns"] = []
    elif args.result_column:
        request["result_columns"] = context_deduplicate(args.result_column)
    if args.max_search_limit is not None:
        request["max_search_limit"] = args.max_search_limit
    request = context_model_payload(
        CollectionUpdateRequest,
        request,
        exclude_unset=True,
    )
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_collections_update(
        project_id,
        args.collection_id,
        request,
        idempotency_key=key,
    )
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_collections_set_default(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_collections_set_default(
        project_id,
        args.collection_id,
        idempotency_key=key,
    )
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_collections_diagnostics(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_collections_diagnostics(project_id, args.collection_id)
    return _context_emit(ctx, payload, context_diagnostics_human)


def handle_context_collections_reindex(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_collections_reindex(
        project_id,
        args.collection_id,
        idempotency_key=key,
    )
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_collections_delete(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    if not args.yes and (ctx.json or not sys.stdin.isatty()):
        raise CliError(
            "CONTEXT_CONFIRMATION_REQUIRED",
            "Non-interactive collection deletion requires --yes.",
            exit_code=USAGE,
        )
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    preview = ctx.client.context_collections_get(project_id, args.collection_id)
    if not ctx.json and not ctx.quiet:
        context_deletion_plan_human(preview)
    if not _context_delete_confirmed(ctx, args.collection_id, args.yes):
        return SUCCESS
    payload = ctx.client.context_collections_delete(
        project_id,
        args.collection_id,
        idempotency_key=key,
    )
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_filters_list(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_filters_list(project_id, args.collection_id)
    return _context_emit(ctx, payload, context_filters_human)


def handle_context_filters_add_column(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    request = context_model_payload(
        FilterColumnRequest,
        {"key": args.key, "column": args.column},
    )
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_filters_add_column(
        project_id,
        args.collection_id,
        request,
        idempotency_key=key,
    )
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_filters_add_jsonb_path(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    request = context_model_payload(
        FilterJsonbPathRequest,
        {"key": args.key, "column": args.column, "path": args.path},
    )
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_filters_add_jsonb_path(
        project_id,
        args.collection_id,
        request,
        idempotency_key=key,
    )
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_points_upsert(ctx: Context, args: argparse.Namespace) -> int:
    return _context_points_mutation(ctx, args, action="upsert")


def handle_context_points_delete(ctx: Context, args: argparse.Namespace) -> int:
    return _context_points_mutation(ctx, args, action="delete")


def _context_points_mutation(
    ctx: Context,
    args: argparse.Namespace,
    *,
    action: str,
) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    keys = context_validate_source_keys(args.source_key)
    request = context_model_payload(PointKeysRequest, {"source_keys": keys})
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    method = (
        ctx.client.context_points_upsert if action == "upsert" else ctx.client.context_points_delete
    )
    payload = method(
        project_id,
        args.collection_id,
        request,
        idempotency_key=key,
    )
    if "operation" not in payload:
        return _context_emit(ctx, payload, context_point_mutation_human)
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_points_status(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_points_status(project_id, args.collection_id)
    return _context_emit(ctx, payload, context_point_status_human)


def handle_context_points_reconcile(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_points_reconcile(
        project_id,
        args.collection_id,
        idempotency_key=key,
    )
    if not ctx.json and not ctx.quiet:
        sys.stderr.write("Final reconciliation may temporarily block writes to the source table.\n")
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_points_scroll(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.collection_id, field="collection_id")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_points_scroll(
        project_id,
        args.collection_id,
        limit=args.limit,
        cursor=args.cursor,
    )
    return _context_emit(ctx, payload, context_points_scroll_human)


def handle_context_operations_list(ctx: Context, args: argparse.Namespace) -> int:
    if args.collection_id:
        context_validate_uuid(args.collection_id, field="collection_id")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_operations_list(
        project_id,
        collection_id=args.collection_id,
        kind=args.kind,
        status=args.status,
        limit=args.limit,
        cursor=args.cursor,
    )
    return _context_emit(ctx, payload, context_operations_list_human)


def handle_context_operations_get(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.operation_id, field="operation_id")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_operations_get(project_id, args.operation_id)
    return _context_emit(ctx, payload, context_operation_human)


def handle_context_operations_wait(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.operation_id, field="operation_id")
    project_id = _resolve_project_id(ctx, None)
    payload = context_wait_for_operation(
        ctx.client,
        project_id=project_id,
        operation_id=args.operation_id,
        timeout_seconds=float(args.timeout),
        poll_interval=args.poll_interval,
        progress=None if ctx.json or ctx.quiet else context_wait_progress,
    )
    return _context_emit(ctx, payload, context_operation_human)


def handle_context_operations_cancel(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.operation_id, field="operation_id")
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_operations_cancel(
        project_id,
        args.operation_id,
        idempotency_key=key,
    )
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_operations_retry(ctx: Context, args: argparse.Namespace) -> int:
    context_validate_uuid(args.operation_id, field="operation_id")
    key = context_idempotency_key(args.idempotency_key)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_operations_retry(
        project_id,
        args.operation_id,
        idempotency_key=key,
    )
    return _context_mutation_result(ctx, args, project_id, payload, key)


def handle_context_count(ctx: Context, args: argparse.Namespace) -> int:
    request = context_model_payload(
        CountRequest,
        {
            "collection": args.collection,
            "filter": _context_filter_input(args),
        },
    )
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_count(project_id, request)
    return _context_emit(ctx, payload, context_count_human)


def handle_context_facets(ctx: Context, args: argparse.Namespace) -> int:
    request = context_model_payload(
        FacetsRequest,
        {
            "collection": args.collection,
            "field": args.field,
            "filter": _context_filter_input(args),
            "limit": args.limit,
        },
    )
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_facets(project_id, request)
    return _context_emit(ctx, payload, context_facets_human)


def handle_context_search(ctx: Context, args: argparse.Namespace) -> int:
    return _context_ranked_request(ctx, args, DenseSearchRequest, "search")


def handle_context_text_hybrid(ctx: Context, args: argparse.Namespace) -> int:
    return _context_ranked_request(ctx, args, TextHybridSearchRequest, "text_hybrid")


def handle_context_graph_first(ctx: Context, args: argparse.Namespace) -> int:
    return _context_ranked_request(ctx, args, GraphFirstSearchRequest, "graph_first")


def handle_context_vector_first(ctx: Context, args: argparse.Namespace) -> int:
    return _context_ranked_request(ctx, args, VectorFirstSearchRequest, "vector_first")


def handle_context_rank_fusion(ctx: Context, args: argparse.Namespace) -> int:
    return _context_ranked_request(ctx, args, RankFusionSearchRequest, "rank_fusion")


def handle_context_joint(ctx: Context, args: argparse.Namespace) -> int:
    request = _context_joint_payload(args)
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_joint(project_id, request)
    _context_reject_ranked_cursor(payload)
    response = context_response_model(ContextJointResponse, payload)
    if ctx.json:
        return _context_emit(ctx, payload, context_joint_human)
    return _context_emit(ctx, response.to_dict(), context_joint_human)


def handle_context_grouped_search(ctx: Context, args: argparse.Namespace) -> int:
    return _context_ranked_request(ctx, args, GroupedSearchRequest, "grouped_search")


def handle_context_recall_check(ctx: Context, args: argparse.Namespace) -> int:
    request = _context_ranked_payload(args, RecallCheckRequest, "recall_check")
    project_id = _resolve_project_id(ctx, None)
    payload = ctx.client.context_recall_check(project_id, request)
    _context_reject_ranked_cursor(payload)
    return _context_emit(ctx, payload, context_recall_human)


def _context_ranked_request(
    ctx: Context,
    args: argparse.Namespace,
    model: type[Any],
    mode: str,
) -> int:
    request = _context_ranked_payload(args, model, mode)
    project_id = _resolve_project_id(ctx, None)
    method = {
        "search": ctx.client.context_search,
        "text_hybrid": ctx.client.context_text_hybrid,
        "graph_first": ctx.client.context_graph_first,
        "vector_first": ctx.client.context_vector_first,
        "rank_fusion": ctx.client.context_rank_fusion,
        "grouped_search": ctx.client.context_grouped_search,
    }[mode]
    payload = method(project_id, request)
    _context_reject_ranked_cursor(payload)
    if payload.get("mode") == "joint":
        raise CliError(
            "CONTEXT_RESPONSE_INVALID",
            "Non-Joint Context endpoint returned Joint response mode.",
            request_id=str(payload.get("request_id") or "") or None,
        )
    return _context_emit(ctx, payload, context_ranked_human)


def _context_reject_ranked_cursor(payload: dict[str, Any]) -> None:
    if {"cursor", "next_cursor", "has_more"}.intersection(payload):
        raise CliError(
            "CONTEXT_RESPONSE_INVALID",
            "Ranked Context response unexpectedly contained a cursor.",
            request_id=str(payload.get("request_id") or "") or None,
        )


def handle_config_path(ctx: Context, args: argparse.Namespace) -> int:
    payload = {"path": str(ctx.store.path)}
    if ctx.json:
        write_json(payload)
    elif not ctx.quiet:
        sys.stdout.write(payload["path"] + "\n")
    return SUCCESS


def handle_notices(ctx: Context, args: argparse.Namespace) -> int:
    display_notices_safely(
        base_url=resolve_api_base_url(ctx.config),
        cli_version=__version__,
        force_refresh=True,
        ignore_display_policy=True,
        show_empty=True,
    )
    return SUCCESS


def _display_post_command_notices(
    *,
    base_url: str | None = None,
    force_refresh: bool = False,
) -> None:
    if base_url is None:
        try:
            config = ConfigStore().load()
            base_url = resolve_api_base_url(config)
        except CliError:
            base_url = os.environ.get("POLYGRES_API_BASE_URL") or DEFAULT_API_BASE_URL
    display_notices_safely(
        base_url=base_url,
        cli_version=__version__,
        force_refresh=force_refresh,
    )


def _context_collection_create_request(args: argparse.Namespace) -> dict[str, Any]:
    body_flags = (
        args.source,
        args.schema,
        args.table,
        args.source_key_column,
        args.vector_column,
        args.content_column,
        args.metadata_column,
        args.dimensions,
        args.metric,
        args.text_column,
        args.result_column,
        args.filter_column,
        args.jsonb_filter,
        args.index_kind,
        args.max_search_limit,
    )
    if args.file:
        if any(value not in (None, [], False) for value in body_flags):
            raise CliError(
                "CONTEXT_REQUEST_INVALID",
                "--file cannot be combined with collection configuration flags.",
                exit_code=USAGE,
            )
        request = context_read_object(args.file, file_input=True, allow_stdin=True)
        if "name" in request:
            raise CliError(
                "CONTEXT_REQUEST_INVALID",
                "The positional collection name is authoritative; remove name from the file.",
                exit_code=USAGE,
            )
        request["name"] = args.name
        return context_model_payload(CollectionCreateRequest, request)
    if args.source is None or args.table is None or args.dimensions is None:
        raise CliError(
            "CONTEXT_REQUEST_INVALID",
            "Flag mode requires --source, --table, and --dimensions.",
            exit_code=USAGE,
        )
    source_key = args.source_key_column or "id"
    if source_key != "id":
        raise CliError(
            "CONTEXT_SOURCE_INVALID",
            "--source-key-column must be id.",
            exit_code=USAGE,
        )
    mode = args.source.replace("-", "_")
    vector_column = args.vector_column
    if mode in {"existing", "add_column"} and vector_column is None:
        raise CliError(
            "CONTEXT_SOURCE_INVALID",
            "--vector-column is required for existing and add-column sources.",
            exit_code=USAGE,
        )
    if mode != "new_table" and (
        args.content_column is not None or args.metadata_column is not None
    ):
        raise CliError(
            "CONTEXT_SOURCE_INVALID",
            "--content-column and --metadata-column are valid only for new-table sources.",
            exit_code=USAGE,
        )
    source: dict[str, Any] = {
        "mode": mode,
        "schema_name": args.schema or "public",
        "table_name": args.table,
        "source_key_column": source_key,
    }
    if mode == "new_table":
        source["content_column"] = args.content_column or "content"
        source["metadata_column"] = args.metadata_column or "metadata"
        vector_column = vector_column or "embedding"
        if args.text_column is not None and args.text_column != source["content_column"]:
            raise CliError(
                "CONTEXT_SOURCE_INVALID",
                "--text-column must equal the generated content column for new-table.",
                exit_code=USAGE,
            )
    request = {
        "name": args.name,
        "source": source,
        "vector": {
            "column_name": vector_column,
            "dimensions": args.dimensions,
            "metric": args.metric or "cosine",
        },
        "text_column": args.text_column,
        "result_columns": context_deduplicate(args.result_column),
        "filter_columns": context_deduplicate(args.filter_column),
        "jsonb_filter_paths": context_parse_jsonb_filters(args.jsonb_filter),
        "index_kind": args.index_kind or "hnsw",
        "max_search_limit": args.max_search_limit or 1000,
    }
    return context_model_payload(CollectionCreateRequest, request)


def _context_ranked_payload(
    args: argparse.Namespace,
    model: type[Any],
    mode: str,
) -> dict[str, Any]:
    if args.request is not None:
        body_fields = (
            "embedding_json",
            "embedding_file",
            "limit",
            "filter_json",
            "filter_file",
            "query",
            "start_schema",
            "start_table",
            "start_id",
            "context_limit",
            "max_depth",
            "graph_limit",
            "relationship_type",
            "direction",
            "context_weight",
            "graph_weight",
            "group_by",
            "group_limit",
            "minimum_recall",
        )
        conflicts = [
            name
            for name in body_fields
            if hasattr(args, name) and getattr(args, name) is not None and getattr(args, name) != []
        ]
        if conflicts:
            raise CliError(
                "CONTEXT_REQUEST_INVALID",
                "--request cannot be combined with request-body flags.",
                exit_code=USAGE,
                details={"fields": conflicts},
            )
        request = context_read_object(args.request, file_input=True, allow_stdin=True)
        if "collection" in request:
            raise CliError(
                "CONTEXT_REQUEST_INVALID",
                "The positional collection is authoritative; remove collection from the request.",
                exit_code=USAGE,
            )
        request["collection"] = args.collection
        if request.get("direction") == "both":
            request["direction"] = "any"
        if mode == "text_hybrid" and (
            not isinstance(request.get("query"), str) or not request["query"].strip()
        ):
            raise CliError(
                "CONTEXT_REQUEST_INVALID",
                "The request query must contain non-whitespace text.",
                exit_code=USAGE,
            )
        return context_model_payload(model, request)

    embedding_json = getattr(args, "embedding_json", None)
    embedding_file = getattr(args, "embedding_file", None)
    if (embedding_json is None) == (embedding_file is None):
        raise CliError(
            "CONTEXT_EMBEDDING_INVALID",
            "Provide exactly one of --embedding-json or --embedding-file.",
            exit_code=USAGE,
        )
    embedding = context_read_array(
        embedding_json if embedding_json is not None else embedding_file,
        file_input=embedding_file is not None,
    )
    request: dict[str, Any] = {
        "collection": args.collection,
        "embedding": context_validate_embedding(embedding),
        "limit": args.limit or 10,
    }
    if hasattr(args, "filter_json"):
        request["filter"] = _context_filter_input(args)
    if mode == "text_hybrid":
        if not args.query or not args.query.strip():
            raise CliError(
                "CONTEXT_REQUEST_INVALID",
                "--query must contain non-whitespace text.",
                exit_code=USAGE,
            )
        request["query"] = args.query
    if mode in {"graph_first", "rank_fusion"}:
        start = (args.start_schema, args.start_table, args.start_id)
        if not all(start):
            raise CliError(
                "CONTEXT_GRAPH_START_REQUIRED",
                "Graph-first and rank-fusion require all graph start flags.",
                exit_code=USAGE,
                details={"mode": mode},
            )
        request["start"] = {
            "schema": args.start_schema,
            "table": args.start_table,
            "id": args.start_id,
        }
    if mode in {"graph_first", "vector_first", "rank_fusion"}:
        request.update(
            {
                "max_depth": args.max_depth or 2,
                "graph_limit": args.graph_limit or 200,
                "relationship_types": context_deduplicate(args.relationship_type),
                "direction": "any" if args.direction in {None, "both"} else args.direction,
            }
        )
    if mode in {"vector_first", "rank_fusion"}:
        request["context_limit"] = args.context_limit or 50
    if mode == "rank_fusion":
        context_weight = 0.7 if args.context_weight is None else args.context_weight
        graph_weight = 0.3 if args.graph_weight is None else args.graph_weight
        context_validate_weights(context_weight, graph_weight)
        request["weights"] = {"context": context_weight, "graph": graph_weight}
    if mode == "grouped_search":
        if not args.group_by:
            raise CliError(
                "CONTEXT_REQUEST_INVALID",
                "--group-by is required.",
                exit_code=USAGE,
            )
        request["group_by"] = args.group_by
        request["group_limit"] = args.group_limit or 1
    if mode == "recall_check":
        request["minimum_recall"] = context_validate_recall(
            0.95 if args.minimum_recall is None else args.minimum_recall
        )
    return context_model_payload(model, request)


def _context_joint_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.request is not None:
        body_fields = (
            "embedding_json",
            "embedding_file",
            "limit",
            "filter_json",
            "filter_file",
            "query",
            "start_json",
            "context_limit",
            "seed_limit",
            "max_depth",
            "graph_limit",
            "traversal_limit",
            "relationship_type",
            "direction",
            "semantic_weight",
            "lexical_weight",
            "graph_weight",
        )
        conflicts = [
            name
            for name in body_fields
            if getattr(args, name) is not None and getattr(args, name) != []
        ]
        if conflicts:
            raise CliError(
                "CONTEXT_REQUEST_INVALID",
                "--request cannot be combined with request-body flags.",
                exit_code=USAGE,
                details={"fields": conflicts},
            )
        request = context_read_object(args.request, file_input=True, allow_stdin=True)
        if "collection" in request:
            raise CliError(
                "CONTEXT_REQUEST_INVALID",
                "The positional collection is authoritative; remove collection from the request.",
                exit_code=USAGE,
            )
        request["collection"] = args.collection
        if request.get("direction") == "both":
            request["direction"] = "any"
        return context_model_payload(JointSearchRequest, request)

    embedding_json = args.embedding_json
    embedding_file = args.embedding_file
    if (embedding_json is None) == (embedding_file is None):
        raise CliError(
            "CONTEXT_EMBEDDING_INVALID",
            "Provide exactly one of --embedding-json or --embedding-file.",
            exit_code=USAGE,
        )
    embedding = context_read_array(
        embedding_json if embedding_json is not None else embedding_file,
        file_input=embedding_file is not None,
    )
    starts = [
        context_read_object(value, file_input=False, code="CONTEXT_REQUEST_INVALID")
        for value in args.start_json
    ]
    semantic_weight = 0.7 if args.semantic_weight is None else args.semantic_weight
    lexical_weight = 0.0 if args.lexical_weight is None else args.lexical_weight
    graph_weight = 0.3 if args.graph_weight is None else args.graph_weight
    context_validate_joint_weights(semantic_weight, lexical_weight, graph_weight)
    request = {
        "collection": args.collection,
        "embedding": context_validate_embedding(embedding),
        "query": args.query,
        "starts": starts,
        "filter": _context_filter_input(args),
        "relationship_types": context_deduplicate(args.relationship_type),
        "direction": "any" if args.direction in {None, "both"} else args.direction,
        "max_depth": args.max_depth or 2,
        "context_limit": args.context_limit or 50,
        "seed_limit": args.seed_limit or 8,
        "graph_limit": args.graph_limit or 200,
        "traversal_limit": args.traversal_limit or 500,
        "weights": {
            "semantic": semantic_weight,
            "lexical": lexical_weight,
            "graph": graph_weight,
        },
        "limit": args.limit or 10,
    }
    return context_model_payload(JointSearchRequest, request)


def _context_filter_input(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.filter_json is not None and args.filter_file is not None:
        raise CliError(
            "CONTEXT_FILTER_INVALID",
            "--filter-json and --filter-file are mutually exclusive.",
            exit_code=USAGE,
        )
    if args.filter_json is not None:
        value = context_read_object(
            args.filter_json,
            file_input=False,
            code="CONTEXT_FILTER_INVALID",
        )
        return context_validate_filter(value)
    if args.filter_file is not None:
        value = context_read_object(
            args.filter_file,
            file_input=True,
            code="CONTEXT_FILTER_INVALID",
        )
        return context_validate_filter(value)
    return None


def _context_mutation_result(
    ctx: Context,
    args: argparse.Namespace,
    project_id: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> int:
    operation = payload.get("operation")
    if not isinstance(operation, dict):
        return _context_emit(ctx, payload, context_point_mutation_human)
    operation_id = operation.get("id")
    if not isinstance(operation_id, str):
        raise CliError(
            "CONTEXT_OPERATION_RESPONSE_INVALID",
            "Context mutation response did not include an operation ID.",
            request_id=str(payload.get("request_id") or "") or None,
        )
    if not args.no_wait:
        payload = context_wait_for_operation(
            ctx.client,
            project_id=project_id,
            operation_id=operation_id,
            timeout_seconds=float(args.timeout),
            initial_envelope=payload,
            progress=None if ctx.json or ctx.quiet else context_wait_progress,
        )
    return _context_emit(
        ctx,
        payload,
        context_operation_human,
        idempotency_key=idempotency_key,
    )


def _context_emit(
    ctx: Context,
    payload: dict[str, Any],
    human: Any,
    **kwargs: Any,
) -> int:
    if ctx.json:
        write_json(payload)
    elif not ctx.quiet:
        human(payload, verbose=bool(ctx.args.verbose), **kwargs)
    return SUCCESS


def _context_delete_confirmed(ctx: Context, collection_id: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise CliError(
            "CONTEXT_CONFIRMATION_REQUIRED",
            "Re-run with --yes to delete the Context collection.",
            exit_code=USAGE,
        )
    sys.stderr.write(f"Delete Context collection {collection_id}? [y/N] ")
    answer = sys.stdin.readline().strip().lower()
    return answer in {"y", "yes"}


def _resolve_project_id(ctx: Context, positional: str | None) -> str:
    candidate = positional or ctx.args.project or ctx.selected_project_id
    if not candidate:
        raise CliError(
            "PROJECT_REQUIRED",
            "Select a project with `polygres projects use <project>` or pass --project.",
            exit_code=USAGE,
        )
    if PROJECT_ID_RE.match(candidate):
        return candidate
    project = _resolve_project(ctx, candidate)
    return _project_api_id(project)


def _guard_synced_project_surface(ctx: Context, args: argparse.Namespace) -> None:
    """Reject prohibited client surfaces from the authoritative project payload.

    The mode lookup is deliberately performed before a handler has a chance to
    request connection information, start ``psql``, or invoke a legacy Runtime
    operation. Existing standard projects continue through their unchanged
    handlers; the server independently enforces the same boundary.
    """
    if getattr(args, "resource", None) not in SYNCED_PROJECT_UNAVAILABLE_RESOURCES:
        return
    candidate = ctx.args.project or ctx.selected_project_id
    if not candidate:
        raise CliError(
            "PROJECT_REQUIRED",
            "Select a project with `polygres projects use <project>` or pass --project.",
            exit_code=USAGE,
        )
    project = _resolve_project(ctx, candidate)
    if _is_synced_project(project):
        raise catalog_cli_error(
            "SYNCED_PROJECT_SURFACE_UNAVAILABLE",
            request_id=_request_id(project),
        )


def _resolve_project(ctx: Context, candidate: str) -> dict[str, Any]:
    cached = ctx._resolved_projects.get(candidate)
    if cached is not None:
        return dict(cached)
    if PROJECT_ID_RE.match(candidate):
        payload = ctx.client.get_project(candidate)
        project = _object(payload, "project")
        project.setdefault("external_id", candidate)
        project.setdefault("id", candidate)
        project["request_id"] = payload.get("request_id")
    else:
        projects_payload = ctx.client.list_projects()
        matches = [
            project
            for project in _items(projects_payload, "projects")
            if project.get("name") == candidate
        ]
        if not matches:
            raise CliError(
                "PROJECT_NOT_FOUND",
                "Project not found. Run `polygres projects list` and retry with a valid "
                "project ID or exact name.",
                exit_code=NOT_FOUND,
                details={"project": candidate},
                request_id=projects_payload.get("request_id"),
            )
        if len(matches) > 1:
            raise CliError(
                "PROJECT_AMBIGUOUS",
                "Project name matches more than one project.",
                exit_code=CONFLICT,
                details={
                    "project": candidate,
                    "matches": [_project_api_id(project) for project in matches],
                },
            )
        project = dict(matches[0])
        project["request_id"] = projects_payload.get("request_id")

    project = _redact_synced_project(project)
    ctx._resolved_projects[candidate] = dict(project)
    project_id = project.get("external_id") or project.get("id")
    if isinstance(project_id, str) and project_id:
        ctx._resolved_projects[project_id] = dict(project)
    return project


def _is_synced_project(project: dict[str, Any]) -> bool:
    """Return whether a public project DTO identifies synchronized mode.

    Older control-plane responses omit ``project_mode``; they remain standard
    for backwards compatibility. Only the authoritative ``synced`` value turns
    on the local safety boundary.
    """
    return project.get("project_mode") == "synced"


def _request_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("request_id")
    return value if isinstance(value, str) and value else None


def _redact_synced_project(project: dict[str, Any]) -> dict[str, Any]:
    """Defensively keep database metadata out of synchronized-project output.

    Control-plane DTOs are responsible for structural redaction. The CLI also
    removes the prohibited fields if it receives an older or malformed payload,
    so a client update cannot turn a backend regression into a terminal leak.
    """
    output = dict(project)
    if not _is_synced_project(output):
        return output
    for field in SYNCED_PROJECT_CONNECTION_FIELDS | SYNCED_PROJECT_CONNECTION_OBJECT_FIELDS:
        output.pop(field, None)
    return output


def _redact_synced_status(status: dict[str, Any]) -> dict[str, Any]:
    """Remove connection state from a synchronized-project status."""
    output = dict(status)
    for field in SYNCED_PROJECT_CONNECTION_FIELDS | {"namespace"}:
        output.pop(field, None)
    for field in ("direct", "pooled"):
        output.pop(field, None)
    return output


def _project_api_id(project: dict[str, Any]) -> str:
    value = project.get("external_id") or project.get("id")
    if isinstance(value, str) and value:
        return value
    raise CliError("PROJECT_INVALID", "Project response did not include an ID.")


def _has_external_ids(projects: list[dict[str, Any]]) -> bool:
    return any(isinstance(project.get("external_id"), str) for project in projects)


def _items(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if isinstance(value, dict):
        return dict(value)
    return {k: v for k, v in payload.items() if k != "request_id"}


def _sanitize_key(key: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in key.items() if k not in {"raw_key", "secret", "api_key"}}


def _normalize_created_key(payload: dict[str, Any]) -> dict[str, Any]:
    key = dict(payload.get("key") or payload.get("api_key") or {})
    if "raw_key" in key:
        key["secret"] = key.pop("raw_key")
    return key


def _database_output(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": payload.get("project_id"),
        "database": payload.get("database"),
        "username": payload.get("username"),
        "port": payload.get("port"),
        "direct_host": payload.get("direct", {}).get("host"),
        "pooled_host": payload.get("pooled", {}).get("host"),
        "ready": payload.get("ready", payload.get("readiness")),
    }


def _emit(ctx: Context, payload: dict[str, Any], human_items: list[tuple[str, Any]]) -> int:
    if ctx.json:
        write_json(redact(payload, allow_key_secret="key" in payload))
    elif not ctx.quiet:
        print_kv(human_items)
    return SUCCESS


def _emit_configuration(
    ctx: Context, payload: dict[str, Any], *, operation: dict[str, Any] | None = None
) -> int:
    output = {
        "configuration": payload.get("configuration", payload.get("graph_configuration", {})),
        "request_id": payload.get("request_id"),
    }
    if operation is not None:
        output["operation"] = operation
    if ctx.json:
        write_json(redact(output))
    elif not ctx.quiet:
        sys.stdout.write(json.dumps(output["configuration"], indent=2, sort_keys=True) + "\n")
    return SUCCESS


def _emit_config_response(
    ctx: Context, payload: dict[str, Any], *, default_operation: dict[str, Any] | None = None
) -> int:
    output = {
        "configuration": payload.get("configuration", {}),
        "request_id": payload.get("request_id"),
    }
    operation = (
        payload.get("operation")
        if isinstance(payload.get("operation"), dict)
        else default_operation
    )
    if operation is not None:
        output["operation"] = operation
    return _emit(ctx, output, [("Configuration", output["configuration"].get("id", ""))])


def _project_status_output(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    resources = payload.get("resources") if isinstance(payload.get("resources"), dict) else {}
    readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}

    if status:
        if not project:
            project = {
                "id": project_id,
                "status": status.get("project") or status.get("status"),
            }
            if "project_mode" in status:
                project["project_mode"] = status["project_mode"]
        if not runtime:
            runtime = {
                key: status[key]
                for key in (
                    "database",
                    "direct_host",
                    "effective_tier_id",
                    "namespace",
                    "pooled_host",
                    "pooler",
                    "runtime_api",
                    "runtime_api_host",
                    "runtime_api_url",
                    "runtime_sync",
                    "traefik",
                )
                if key in status
            }
        if not resources:
            resources = {
                key: status[key] for key in ("last_storage_measurement", "memory") if key in status
            }
        if not readiness:
            readiness = {
                key: status[key] for key in ("graph", "hybrid", "text", "vector") if key in status
            }

    if not project and payload.get("project_mode") == "synced":
        project = {"id": project_id, "project_mode": "synced"}
    project = _redact_synced_project(project)
    if _is_synced_project(project):
        runtime = _redact_synced_status(runtime)
        readiness = _redact_synced_status(readiness)

    output = {
        "project": project,
        "runtime": runtime,
        "resources": resources,
        "readiness": readiness,
        "request_id": payload.get("request_id"),
    }
    return output


def _poll_project_status(ctx: Context, project_id: str, *, deadline: float) -> dict[str, Any]:
    last_status: dict[str, Any] = {}
    while time.monotonic() <= deadline:
        payload = ctx.client.get_project_status(project_id, deadline=deadline)
        status = (
            payload.get("status")
            if isinstance(payload.get("status"), dict)
            else payload.get("project", {})
        )
        last_status = status if isinstance(status, dict) else {}
        project_status = last_status.get("project") or last_status.get("status")
        if project_status in {"ready", "read_only"}:
            return last_status
        if project_status == "failed":
            raise CliError(
                "PROJECT_PROVISIONING_FAILED",
                f"Project {project_id} could not be provisioned. Run "
                f"`polygres projects status {project_id}` to inspect the failure; "
                "contact support if the status does not provide a corrective action.",
            )
        if project_status in {"suspended", "deleting"}:
            raise CliError(
                "PROJECT_UNAVAILABLE", f"Project is {project_status}.", exit_code=CONFLICT
            )
        if project_status == "deleted":
            raise CliError("PROJECT_NOT_FOUND", "Project was deleted.", exit_code=NOT_FOUND)
        _write_poll_progress(ctx, "Project", project_id, last_status)
        _sleep_until_deadline(_poll_interval(payload), deadline)
    raise CliError(
        "TIMEOUT",
        f"Timed out waiting for project {project_id}; last status is still in progress.",
        exit_code=UNAVAILABLE,
        details={"status": last_status},
    )


def _sync_source_connection(ctx: Context, args: argparse.Namespace) -> dict[str, Any]:
    return build_source_connection(
        connection_environment=args.connection_env,
        host=args.host,
        port=args.port,
        database=args.database,
        username=args.username,
        password_environment=args.password_env,
        environment=os.environ,
        prompt_secret=getpass.getpass,
        interactive=sys.stdin.isatty() and not ctx.json,
    )


def _require_sync_enabled(options: dict[str, Any]) -> None:
    enabled = options.get("synced_projects_enabled")
    if not isinstance(enabled, bool):
        raise CliError(
            "SYNC_CREATION_OPTIONS_INVALID",
            "The API did not return sync-project availability.",
        )
    if enabled:
        return
    reason = options.get("disabled_reason")
    message = "Synchronized project creation is not currently enabled."
    if isinstance(reason, str) and reason:
        message = f"{message} {reason}"
    raise CliError("SYNC_CREATION_DISABLED", message, exit_code=CONFLICT)


def _sync_create_selections(
    ctx: Context,
    args: argparse.Namespace,
    available_tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if args.file:
        return load_sync_selection(_readable_file(args.file))
    if args.tables:
        return automatic_sync_selection(args.tables, available_tables)

    selectable = [
        table
        for table in available_tables
        if table.get("schema_name") == "public"
        and table.get("eligible") is True
        and (isinstance(table.get("sync_key"), dict) or bool(table.get("sync_key_candidates")))
    ]
    if not selectable:
        raise CliError(
            "SYNC_TABLE_SELECTION_UNAVAILABLE",
            "The source inspection found no fully eligible tables with a usable sync key.",
            exit_code=CONFLICT,
        )
    selectable_names = [
        f"{table.get('schema_name')}.{table.get('table_name')}" for table in selectable
    ]
    if args.all_eligible:
        return automatic_sync_selection(selectable_names, available_tables)
    if not sys.stdin.isatty() or ctx.json:
        raise CliError(
            "SYNC_TABLE_SELECTION_REQUIRED",
            "Select at least one table with --table, --file, or --all-eligible.",
            exit_code=USAGE,
        )

    if not ctx.quiet:
        rows = [
            {
                "table": name,
                "sync_key": _sync_table_key_summary(table),
                "estimated_rows": table.get("estimated_rows"),
                "estimated_bytes": table.get("estimated_total_bytes"),
            }
            for name, table in zip(selectable_names, selectable, strict=True)
        ]
        print_table(rows, ["table", "sync_key", "estimated_rows", "estimated_bytes"])
    sys.stderr.write("Select tables (comma-separated schema.table values, or 'all'): ")
    answer = sys.stdin.readline().strip()
    if answer.lower() == "all":
        selected_names = selectable_names
    else:
        selected_names = [value.strip() for value in answer.split(",") if value.strip()]
    if not selected_names:
        raise CliError(
            "SYNC_TABLE_SELECTION_REQUIRED",
            "At least one source table must be selected.",
            exit_code=USAGE,
        )
    return automatic_sync_selection(selected_names, available_tables)


def _sync_source_inspection_error(
    preflight: dict[str, Any],
    options: dict[str, Any],
    *,
    idempotency_key: str,
) -> CliError:
    failure = preflight.get("failure") if isinstance(preflight.get("failure"), dict) else {}
    code = str(failure.get("code") or "SYNC_SOURCE_INSPECTION_FAILED")
    message = str(failure.get("message") or "The source database did not pass sync checks.")
    egress_ips = options.get("egress_ips") if isinstance(options.get("egress_ips"), list) else []
    allowlist = [
        str(value.get("ip")) for value in egress_ips if isinstance(value, dict) and value.get("ip")
    ]
    if allowlist:
        message += " Ensure the source allows connections from: " + ", ".join(allowlist) + "."
    return CliError(
        code,
        message,
        details={
            "checks": preflight.get("checks", []),
            "source_allowlist_ips": allowlist,
            "idempotency_key": idempotency_key,
        },
    )


def _sync_preflight(payload: dict[str, Any]) -> dict[str, Any]:
    preflight = payload.get("preflight")
    if not isinstance(preflight, dict):
        raise CliError(
            "SYNC_CREATION_RESPONSE_INVALID",
            "The API returned an invalid source-inspection response. Retry the command; contact "
            "support if it happens again.",
            request_id=str(payload.get("request_id") or "") or None,
        )
    return preflight


def _sync_generation(preflight: dict[str, Any], field: str) -> int:
    value = preflight.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CliError(
            "SYNC_CREATION_RESPONSE_INVALID",
            f"The API response did not include a valid {field}.",
        )
    return value


def _poll_sync_preflight(
    ctx: Context, initial_payload: dict[str, Any], *, deadline: float
) -> dict[str, Any]:
    payload = initial_payload
    preflight = _sync_preflight(payload)
    attempt_id = preflight.get("attempt_id")
    if not isinstance(attempt_id, str) or not PREFLIGHT_ATTEMPT_ID_RE.fullmatch(attempt_id):
        raise CliError(
            "SYNC_CREATION_RESPONSE_INVALID",
            "The API response did not include a valid internal source-inspection token.",
            request_id=str(payload.get("request_id") or "") or None,
        )
    terminal = {
        "source_ready",
        "connection_failed",
        "admitted",
        "rejected",
        "cancelled",
        "expired",
    }
    while time.monotonic() <= deadline:
        status = preflight.get("status")
        if status in terminal:
            return payload
        _write_source_inspection_progress(ctx, preflight)
        _sleep_until_deadline(_poll_interval(payload), deadline)
        if time.monotonic() >= deadline:
            break
        payload = ctx.client.get_project_preflight(attempt_id, deadline=deadline)
        preflight = _sync_preflight(payload)
    raise CliError(
        "TIMEOUT",
        "Timed out while inspecting the source database. Re-run the same creation command with "
        "the same --idempotency-key to resume safely.",
        exit_code=UNAVAILABLE,
        details={"status": preflight.get("status")},
    )


def _write_source_inspection_progress(ctx: Context, inspection: dict[str, Any]) -> None:
    if ctx.json or ctx.quiet:
        return
    status = inspection.get("status") or "in progress"
    sys.stderr.write(f"Source inspection: {status}\n")


def _list_all_preflight_tables(
    ctx: Context,
    attempt_id: str,
    *,
    cursor: str | None,
    limit: int,
    all_pages: bool,
) -> tuple[list[dict[str, Any]], str | None, object]:
    tables: list[dict[str, Any]] = []
    next_cursor = cursor
    request_id: object = None
    seen_cursors: set[str] = set()
    while True:
        payload = ctx.client.list_project_preflight_tables(
            attempt_id,
            cursor=next_cursor,
            limit=limit,
        )
        tables.extend(_items(payload, "tables"))
        request_id = payload.get("request_id") or request_id
        value = payload.get("next_cursor")
        next_cursor = value if isinstance(value, str) and value else None
        if not all_pages or next_cursor is None:
            return tables, next_cursor, request_id
        if next_cursor in seen_cursors:
            raise CliError(
                "SYNC_TABLE_PAGINATION_INVALID",
                "The API returned a repeated sync table cursor.",
            )
        seen_cursors.add(next_cursor)


def _sync_table_key_summary(table: dict[str, Any]) -> str:
    sync_key = table.get("sync_key")
    if isinstance(sync_key, dict):
        columns = sync_key.get("columns")
        if isinstance(columns, list):
            return f"{sync_key.get('kind', 'key')} ({', '.join(str(value) for value in columns)})"
        return str(sync_key.get("kind") or "key")
    candidates = table.get("sync_key_candidates")
    if isinstance(candidates, list) and candidates:
        return f"{len(candidates)} unique candidate(s)"
    return ""


def _require_sync_create_ready(preflight: dict[str, Any]) -> None:
    status = preflight.get("status")
    if status not in {"source_ready", "admitted"}:
        raise CliError(
            "SYNC_SOURCE_NOT_READY",
            "The source database has not completed sync admission checks.",
            exit_code=CONFLICT,
        )
    selection = preflight.get("selection")
    selected_count = selection.get("selected_count") if isinstance(selection, dict) else 0
    if (
        isinstance(selected_count, bool)
        or not isinstance(selected_count, int)
        or selected_count < 1
    ):
        raise CliError(
            "SYNC_SELECTION_REQUIRED",
            "No source tables were selected for synchronization.",
            exit_code=CONFLICT,
        )
    valid_actions = preflight.get("valid_actions")
    if (
        status == "source_ready"
        and isinstance(valid_actions, list)
        and "create_project" not in valid_actions
    ):
        raise CliError(
            "SYNC_SOURCE_NOT_ADMISSIBLE",
            "The source database is not currently eligible for project creation.",
            exit_code=CONFLICT,
        )


def _project_create_wait_error(
    *,
    project: dict[str, Any],
    project_id: str,
    create_request_id: object,
    cause: CliError,
) -> CliError:
    if cause.code not in {"SERVICE_UNAVAILABLE", "TIMEOUT"} and cause.exit_code != UNAVAILABLE:
        return cause
    project_name = project.get("name")
    project_status = project.get("status")
    details: dict[str, Any] = {
        "project": {
            "id": project.get("id"),
            "external_id": project.get("external_id") or project_id,
            "name": project_name,
            "status": project_status,
        },
        "create_request_id": create_request_id,
        "wait_error": {
            "code": cause.code,
            "message": cause.message,
            "details": cause.details,
            "request_id": cause.request_id,
        },
    }
    details["project"] = {
        key: value for key, value in details["project"].items() if value is not None
    }
    code = (
        "PROJECT_READINESS_TIMEOUT" if cause.code == "TIMEOUT" else "PROJECT_READINESS_UNAVAILABLE"
    )
    message = (
        f"Project {project_id} was created but readiness polling timed out."
        if cause.code == "TIMEOUT"
        else f"Project {project_id} was created but readiness polling failed."
    )
    message += f" Run `polygres projects status {project_id}` to resume validation or cleanup."
    return CliError(
        code,
        message,
        exit_code=UNAVAILABLE,
        details=details,
        request_id=cause.request_id or str(create_request_id or ""),
    )


def _poll_import(
    ctx: Context, project_id: str, job_id: str, timeout_seconds: int, previous: dict[str, Any]
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    interval_payload = previous
    last_output = _import_output(previous)
    last_progress: str | None = None
    while time.monotonic() < deadline:
        progress = json.dumps(last_output["import"], sort_keys=True, default=str)
        if progress != last_progress:
            _write_poll_progress(ctx, "Import", job_id, last_output["import"])
            last_progress = progress
        _sleep_until_deadline(_poll_interval(interval_payload), deadline)
        if time.monotonic() >= deadline:
            break
        payload = ctx.client.get_import(project_id, job_id, deadline=deadline)
        output = _import_output(payload)
        if output["import"].get("status") in {"succeeded", "failed", "cancelled"}:
            return output
        interval_payload = payload
        last_output = output
    raise CliError(
        "TIMEOUT",
        f"Timed out waiting for import {job_id}; it is still in progress.",
        exit_code=UNAVAILABLE,
        details={"import": last_output["import"], "request_id": last_output.get("request_id")},
    )


def _poll_interval(payload: dict[str, Any]) -> int:
    value = payload.get("poll_interval_seconds", 2)
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = 2
    return min(max(seconds, 1), 30)


def _import_output(payload: dict[str, Any]) -> dict[str, Any]:
    item = payload.get("import") or payload.get("job") or {}
    return {"import": item, "request_id": payload.get("request_id")}


def _write_import_human(output: dict[str, Any]) -> None:
    item = output["import"]
    sys.stdout.write(f"Import {item.get('id')} {item.get('status')}\n")
    request_id = output.get("request_id")
    if request_id:
        sys.stdout.write(f"Request ID: {request_id}\n")
    if item.get("status") != "failed":
        return
    error = item.get("error") if isinstance(item.get("error"), dict) else {}
    error_code = item.get("error_code") or error.get("code")
    error_message = item.get("error_message") or error.get("message")
    if error_code:
        sys.stdout.write(f"Error code: {error_code}\n")
    if error_message:
        sys.stdout.write(f"Error message: {error_message}\n")
    for label, key in [
        ("Row errors", "row_errors"),
        ("Row details", "row_details"),
        ("Details", "details"),
        ("Errors", "errors"),
    ]:
        value = item.get(key)
        if value:
            sys.stdout.write(f"{label}: {json.dumps(value, sort_keys=True)}\n")
    progress = item.get("progress") if isinstance(item.get("progress"), dict) else {}
    for label, key in [
        ("SQL state", "sqlstate"),
        ("Detail", "detail"),
        ("Progress row errors", "row_errors"),
        ("Progress details", "details"),
    ]:
        value = progress.get(key)
        if value:
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, sort_keys=True)
            else:
                rendered = str(value)
            sys.stdout.write(f"{label}: {rendered}\n")


def _import_exit_code(item: dict[str, Any]) -> int:
    status = item.get("status")
    if status == "succeeded":
        return SUCCESS
    if status == "failed":
        return GENERAL_FAILURE
    if status == "cancelled":
        return CONFLICT
    if status in {"queued", "running"}:
        return SUCCESS
    return GENERAL_FAILURE


def _latest_import_id(imports: list[dict[str, Any]]) -> str | None:
    if not imports:
        return None
    imports.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("updated_at") or ""),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    job_id = imports[0].get("id")
    if not isinstance(job_id, str):
        raise CliError(
            "IMPORT_INVALID",
            "The latest import record has no ID. Run `polygres import status <job_id>` "
            "with the ID from the original import output; contact support if no ID was returned.",
        )
    return job_id


def _require_confirmation(ctx: Context, yes: bool, prompt: str) -> None:
    if yes:
        return
    if sys.stdin.isatty():
        sys.stderr.write(prompt + " Type 'yes' to continue: ")
        if sys.stdin.readline().strip() == "yes":
            return
    raise CliError(
        "CONFIRMATION_REQUIRED",
        "Re-run with --yes to confirm.",
        exit_code=USAGE,
    )


def _readable_file(value: str) -> Path:
    path = Path(value)
    if not path.exists() or not path.is_file():
        raise CliError(
            "VALIDATION_ERROR",
            f"File does not exist or is not a regular file: {path}",
            exit_code=USAGE,
        )
    try:
        with path.open("rb"):
            pass
    except OSError as exc:
        raise CliError(
            "VALIDATION_ERROR", f"File is not readable: {path}", exit_code=USAGE
        ) from exc
    return path


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CliError(
            "VALIDATION_ERROR",
            f"File is not readable UTF-8 text: {path}",
            exit_code=USAGE,
        ) from exc


def _json_object_file(value: str) -> dict[str, Any]:
    path = _readable_file(value)
    try:
        payload = json.loads(_read_text_file(path))
    except json.JSONDecodeError as exc:
        raise CliError(
            "VALIDATION_ERROR",
            f"Invalid JSON file: {path}. Fix the JSON syntax near line {exc.lineno}, "
            f"column {exc.colno}, then retry.",
            exit_code=USAGE,
        ) from exc
    if not isinstance(payload, dict):
        raise CliError(
            "VALIDATION_ERROR",
            "JSON file must contain an object at the top level. Wrap the fields in `{}` and retry.",
            exit_code=USAGE,
        )
    return payload


def _graph_configuration_file(value: str) -> dict[str, Any]:
    payload = _json_object_file(value)
    if "configuration" not in payload:
        configuration = payload
    else:
        allowed_wrapper_keys = {"configuration", "request_id"}
        extra_keys = sorted(set(payload) - allowed_wrapper_keys)
        if extra_keys:
            raise CliError(
                "VALIDATION_ERROR",
                "Graph configuration export contains unsupported wrapper fields.",
                exit_code=USAGE,
                details={"fields": extra_keys},
            )
        configuration = payload["configuration"]
        if configuration is None:
            raise CliError(
                "GRAPH_CONFIGURATION_EMPTY",
                "Graph configuration export does not contain an applyable configuration.",
                exit_code=USAGE,
            )
        if not isinstance(configuration, dict):
            raise CliError(
                "VALIDATION_ERROR",
                "Graph configuration must contain an object.",
                exit_code=USAGE,
            )
    _reject_unknown_fields(
        configuration,
        GRAPH_CONFIGURATION_KEYS | GRAPH_CONFIGURATION_READ_ONLY_KEYS,
        "graph configuration",
    )
    request_configuration = {
        key: configuration[key] for key in GRAPH_CONFIGURATION_KEYS if key in configuration
    }
    _validate_graph_configuration(request_configuration)
    return _canonicalize_graph_id_columns(request_configuration)


def _graph_discovery_configuration(payload: dict[str, Any]) -> dict[str, Any]:
    node_tables = payload.get("node_tables", [])
    relationships = payload.get("relationships", [])
    filter_columns = payload.get("filter_columns", [])
    if not all(isinstance(value, list) for value in (node_tables, relationships, filter_columns)):
        raise CliError(
            "GRAPH_DISCOVERY_INVALID",
            "Graph discovery response contains invalid candidate arrays.",
        )
    configuration = {
        "registered_tables": [
            {
                key: item[key]
                for key in (
                    "schema",
                    "table",
                    "id_column",
                    "id_columns",
                    "columns",
                    "tenant_column",
                )
                if key in item
            }
            if isinstance(item, dict)
            else item
            for item in node_tables
        ],
        "registered_relationships": [
            {
                key: item[key]
                for key in (
                    "from_schema",
                    "from_table",
                    "from_column",
                    "to_schema",
                    "to_table",
                    "to_column",
                    "label",
                    "bidirectional",
                )
                if key in item
            }
            if isinstance(item, dict)
            else item
            for item in relationships
        ],
        "filter_columns": [
            {key: item[key] for key in ("schema", "table", "column", "type") if key in item}
            if isinstance(item, dict)
            else item
            for item in filter_columns
        ],
        "runtime_settings": {},
    }
    try:
        _validate_graph_configuration(configuration)
    except CliError as exc:
        raise CliError(
            "GRAPH_DISCOVERY_INVALID",
            f"Graph discovery response is not applyable: {exc.message}",
            details=exc.details,
        ) from exc
    return _canonicalize_graph_id_columns(configuration)


def _canonicalize_graph_id_columns(
    configuration: dict[str, Any],
) -> dict[str, Any]:
    for table in configuration.get("registered_tables", []):
        if not isinstance(table, dict):
            continue
        legacy_id_column = table.pop("id_column", None)
        if legacy_id_column:
            table["id_columns"] = [legacy_id_column]
    return configuration


def _validate_graph_configuration(configuration: dict[str, Any]) -> None:
    _reject_unknown_fields(configuration, GRAPH_CONFIGURATION_KEYS, "graph configuration")
    for key in ("registered_tables", "registered_relationships", "filter_columns"):
        value = configuration.get(key, [])
        if not isinstance(value, list):
            _graph_invalid(f"{key} must be an array.")
    runtime_settings = configuration.get("runtime_settings", {})
    if not isinstance(runtime_settings, dict):
        _graph_invalid("runtime_settings must be an object.")

    table_keys = {"schema", "table", "id_column", "id_columns", "columns", "tenant_column"}
    for index, item in enumerate(configuration.get("registered_tables", [])):
        if not isinstance(item, dict):
            _graph_invalid(f"registered_tables[{index}] must be an object.")
        _reject_unknown_fields(item, table_keys, f"registered_tables[{index}]")
        _required_string(item, "table", f"registered_tables[{index}]")
        for key in ("schema", "id_column", "tenant_column"):
            if key in item and item[key] is not None:
                _graph_identifier(item[key], f"registered_tables[{index}].{key}")
        for key in ("id_columns", "columns"):
            values = item.get(key, [])
            if not isinstance(values, list):
                _graph_invalid(f"registered_tables[{index}].{key} must be an array.")
            for value in values:
                _graph_identifier(value, f"registered_tables[{index}].{key}")
        has_single = isinstance(item.get("id_column"), str) and bool(item["id_column"])
        has_multiple = bool(item.get("id_columns"))
        if has_single == has_multiple:
            _graph_invalid(
                f"registered_tables[{index}] must use exactly one of id_column or id_columns."
            )

    relationship_keys = {
        "from_schema",
        "from_table",
        "from_column",
        "to_schema",
        "to_table",
        "to_column",
        "label",
        "bidirectional",
    }
    for index, item in enumerate(configuration.get("registered_relationships", [])):
        if not isinstance(item, dict):
            _graph_invalid(f"registered_relationships[{index}] must be an object.")
        _reject_unknown_fields(item, relationship_keys, f"registered_relationships[{index}]")
        for key in ("from_table", "from_column", "to_table", "to_column", "label"):
            _required_string(item, key, f"registered_relationships[{index}]")
        for key in ("from_schema", "to_schema"):
            if key in item:
                _graph_identifier(item[key], f"registered_relationships[{index}].{key}")
        if "bidirectional" in item and not isinstance(item["bidirectional"], bool):
            _graph_invalid(f"registered_relationships[{index}].bidirectional must be boolean.")

    filter_keys = {"schema", "table", "column", "type"}
    filter_types = {"numeric", "boolean", "text", "date", "timestamptz", "uuid"}
    for index, item in enumerate(configuration.get("filter_columns", [])):
        if not isinstance(item, dict):
            _graph_invalid(f"filter_columns[{index}] must be an object.")
        _reject_unknown_fields(item, filter_keys, f"filter_columns[{index}]")
        for key in ("table", "column"):
            _required_string(item, key, f"filter_columns[{index}]")
        if "schema" in item:
            _graph_identifier(item["schema"], f"filter_columns[{index}].schema")
        if item.get("type") not in filter_types:
            _graph_invalid(f"filter_columns[{index}].type is invalid.")


def _reject_unknown_fields(item: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(item) - allowed)
    if unknown:
        _graph_invalid(f"{label} contains unknown fields.", {"fields": unknown})


def _required_string(item: dict[str, Any], key: str, label: str) -> None:
    if key not in item:
        _graph_invalid(f"{label}.{key} is required.")
    _graph_identifier(item[key], f"{label}.{key}")


def _graph_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or not SQL_IDENTIFIER_RE.fullmatch(value):
        _graph_invalid(f"{label} must be a valid SQL identifier.")


def _graph_invalid(message: str, details: dict[str, Any] | None = None) -> None:
    raise CliError(
        "GRAPH_CONFIGURATION_INVALID",
        message,
        exit_code=USAGE,
        details=details or {},
    )


def _validate_uuid(value: str, label: str) -> None:
    if not UUID_LIKE_RE.match(value):
        raise CliError("VALIDATION_ERROR", f"Invalid {label}.", exit_code=USAGE)


def _validate_text_config_ref(value: str) -> None:
    if UUID_LIKE_RE.fullmatch(value) or (
        value == value.strip()
        and 0 < len(value) <= 80
        and not any(character in value for character in ("/", "?", "#", "\x00"))
    ):
        return
    raise CliError(
        "VALIDATION_ERROR",
        "Invalid text configuration ID or name.",
        exit_code=USAGE,
    )


def _validate_text_limits(default_limit: int, max_limit: int) -> None:
    if default_limit > max_limit:
        raise CliError(
            "VALIDATION_ERROR",
            "Default limit cannot exceed max limit.",
            exit_code=USAGE,
        )


def _validate_response_uuid(value: object, label: str) -> None:
    if not isinstance(value, str) or not UUID_LIKE_RE.fullmatch(value):
        raise CliError(
            "MIGRATION_INVALID" if "migration" in label else "IMPORT_INVALID",
            f"{label.capitalize()} response did not include a valid ID.",
        )


def _validate_migration_name(value: str) -> None:
    if not MIGRATION_NAME_RE.match(value):
        raise CliError("VALIDATION_ERROR", "Invalid migration name.", exit_code=USAGE)


def _validate_identifiers(*values: str | None) -> None:
    for value in values:
        if value is not None and not SQL_IDENTIFIER_RE.match(value):
            raise CliError("VALIDATION_ERROR", f"Invalid SQL identifier: {value}", exit_code=USAGE)


def _migration_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = "migration"
    if not re.match(r"^[A-Za-z_]", normalized):
        normalized = f"m_{normalized}"
    _validate_migration_name(normalized)
    return normalized


def _timeout_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be an integer") from exc
    if seconds < 1 or seconds > 86400:
        raise argparse.ArgumentTypeError("timeout must be between 1 and 86400")
    return seconds


def _context_admin_limit(value: str) -> int:
    return _context_bounded_integer(value, label="limit", minimum=1, maximum=100)


def _text_limit(value: str) -> int:
    return _context_bounded_integer(value, label="text limit", minimum=1, maximum=1000)


def _context_ranked_limit(value: str) -> int:
    return _context_bounded_integer(value, label="limit", minimum=1, maximum=1000)


def _context_graph_depth(value: str) -> int:
    return _context_bounded_integer(value, label="max depth", minimum=1, maximum=20)


def _context_joint_seed_limit(value: str) -> int:
    return _context_bounded_integer(value, label="seed limit", minimum=1, maximum=32)


def _context_dimensions(value: str) -> int:
    return _context_bounded_integer(value, label="dimensions", minimum=1, maximum=16000)


def _context_bounded_integer(
    value: str,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise argparse.ArgumentTypeError(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _context_finite_float(value: str) -> float:
    try:
        return context_finite_number(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _context_poll_interval_arg(value: str) -> float:
    parsed = _context_finite_float(value)
    if parsed < 0.5 or parsed > 30:
        raise argparse.ArgumentTypeError("poll interval must be between 0.5 and 30")
    return parsed


def _dimensions(value: str) -> int:
    try:
        dimensions = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("dimensions must be an integer") from exc
    if dimensions < 1 or dimensions > 2000:
        raise argparse.ArgumentTypeError("dimensions must be between 1 and 2000")
    return dimensions


def _similarity_threshold(value: str) -> float:
    try:
        threshold = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("similarity threshold must be a number") from exc
    if threshold < 0 or threshold > 1:
        raise argparse.ArgumentTypeError("similarity threshold must be between 0 and 1")
    return threshold


def _one_char(value: str) -> str:
    if len(value) != 1:
        raise argparse.ArgumentTypeError("value must be one character")
    return value


def _delimiter(value: str) -> str:
    value = _one_char(value)
    if value not in {",", "\t", ";", "|"}:
        raise argparse.ArgumentTypeError("delimiter must be comma, tab, semicolon, or pipe")
    return value


def _remove_pgbouncer_query(value: object) -> object:
    value = _passwordless_url(value)
    if not isinstance(value, str):
        return value
    parsed = urlsplit(value)
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not (key.lower() == "pgbouncer" and item.lower() == "true")
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _passwordless_url(value: object) -> object:
    if not isinstance(value, str):
        return value
    parsed = urlsplit(value)
    if parsed.username is None:
        return value
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    netloc = f"{parsed.username}@{host}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _summary_value(value: object) -> str:
    if not isinstance(value, dict):
        return str(value or "")
    for key in ("status", "ready", "runtime_status", "project"):
        if key in value:
            return str(value[key])
    return json.dumps(value, sort_keys=True) if value else ""


def _graph_difference_summary(value: object) -> str:
    if not isinstance(value, list):
        return ""
    summaries: list[str] = []
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "unknown")[:80]
        reason = str(item.get("reason") or "mismatch")[:80]
        summaries.append(f"{field} ({reason})")
    return ", ".join(summaries)


def _resource_pressure(resources: dict[str, Any]) -> str:
    for key in ("pressure", "resource_pressure", "memory_pressure", "status"):
        if key in resources:
            return str(resources[key])
    memory = resources.get("memory")
    if isinstance(memory, dict):
        return _resource_pressure(memory)
    return _summary_value(resources)


def _sleep_until_deadline(seconds: float, deadline: float) -> None:
    remaining = max(deadline - time.monotonic(), 0.0)
    delay = min(float(seconds), remaining)
    if delay > 0:
        time.sleep(delay)


def _write_poll_progress(
    ctx: Context, operation: str, identifier: str, status: dict[str, Any]
) -> None:
    if ctx.json or ctx.quiet:
        return
    state = status.get("status") or status.get("project") or "in progress"
    progress = status.get("progress")
    suffix = f" {json.dumps(progress, sort_keys=True)}" if isinstance(progress, dict) else ""
    sys.stderr.write(f"{operation} {identifier}: {state}{suffix}\n")
