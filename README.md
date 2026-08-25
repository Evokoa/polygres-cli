# Polygres CLI

Use the Polygres CLI to manage projects, load data, apply migrations, and configure retrieval from your terminal.

The CLI signs in through the Polygres dashboard. It does not expose database passwords.

- [Documentation](https://docs.polygres.com/cli)
- [Polygres](https://polygres.com)

## Install

Install the CLI with pip:

```bash
pip install polygres-cli
```

For an isolated global installation, use pipx:

```bash
pipx install polygres-cli
```

The installed command is `polygres`.

## Get started

Sign in, choose a project, and check that it is ready:

```bash
polygres login
polygres whoami
polygres projects list
polygres projects use <project-id-or-exact-name>
polygres ready
```

`polygres login` opens the dashboard for approval. On a headless terminal, it prints a URL that you can open in another browser. Run `polygres logout` when you want to revoke the session and remove the local credentials.

## Synchronized PostgreSQL projects

Create a synchronized project with one command:

```bash
# Set SOURCE_DATABASE_URL through your shell or secret manager, then reference
# the variable by name so the URL is not passed as a command argument.
polygres projects create sync analytics \
  --connection-env SOURCE_DATABASE_URL \
  --table public.customers \
  --table public.orders \
  --yes
```

The command checks sync availability, inspects the source, discovers and selects
tables, creates the project, and waits for readiness. Use `--all-eligible` instead
of repeated `--table` options to synchronize every fully eligible discovered
table. In an interactive terminal, omitting all table-selection options opens a
selection prompt.

The command accepts either a PostgreSQL URL through `--connection-env NAME`, or
structured `--host`, `--database`, `--username`, and `--password-env NAME`
options. In an interactive terminal, the URL or structured password can instead
be entered through a hidden prompt. The CLI intentionally has no plaintext URL
or password argument.

For explicit unique-key choices or partial-table sync, pass `--file
selection.json`. The file contains a `tables` array using `schema_name`,
`table_name`, optional `sync_key_index_name`, and optional `included_columns`
fields. Pass `--idempotency-key` to safely resume the full workflow after an
ambiguous timeout.

Projects whose control-plane payload has `project_mode: "synced"` do not expose
database connection metadata. The CLI rejects `db info`, `db psql`, and `env`
with `SYNCED_PROJECT_SURFACE_UNAVAILABLE` (permission exit code `4`) before it
opens a database client. Readiness, vector, hybrid, graph, text-search, and
pgContext (`context`) commands remain available when the project is ready.

The existing standard-project shorthand remains supported:

```bash
polygres projects create <name>
```

## Common workflows

### Load data and apply migrations

```bash
polygres import csv ./documents.csv --table documents --wait
polygres migrations apply --file ./001_create_documents.sql
```

### Configure retrieval

```bash
polygres graph discover --json > graph.json
polygres graph config apply --file graph.json
polygres vector configs list
polygres text configs list
```

Creating new pgvector configurations is retired. Use
`polygres context collections create` to create a pgContext collection and native
`pgcontext.vector` column. Existing vector configuration list, retrieval, and lifecycle
commands remain available for previously registered columns.

### Work with pgContext AI Search

pgContext uses named collections and is the supported path for new vector setup.

```bash
polygres context capabilities
polygres context sources discover
polygres context collections create support_docs \
  --source new-table \
  --table support_docs \
  --dimensions 768
polygres context search support_docs \
  --embedding-file query-embedding.json
```

Commands that change a collection wait for the server operation to finish by default. Use `--no-wait` to return as soon as the operation is accepted.

Global options must come before the command namespace:

```bash
polygres --project <project-id> --json context collections list
```

## Use additional API routes

The `api` commands give automation access to supported project-management routes that do not yet have a dedicated high-level command.

```bash
polygres api routes
polygres --json api routes --method GET
polygres --json --project <project-id> api request \
  /projects/{project_id} \
  --method GET \
  --dry-run
```

The CLI validates the route, HTTP method, parameters, and JSON body against its bundled API specification before sending the request. Run with `--dry-run` to inspect a request without executing it.

## Single-row writes

Write one JSON object through the Runtime API without opening a database
connection. Use a named file or `--file -` for standard input.

```bash
polygres --project <project-id> rows upsert \
  --schema public --table memories --file row.json \
  --conflict-column id --returning id

printf '%s' '{"id":"memory_123","content":"hello"}' | \
  polygres --project <project-id> rows upsert \
  --table memories --file - --conflict-column id
```

Context behavior is never inferred for an ordinary table. Pass
`--context-collection <uuid>` or `--reconcile-context` to make the same command
write the row and reconcile one pgContext point. Context-backed commands wait by
default and display a resumable idempotency key; `--no-wait` returns the durable
operation ID.

## Notices and automation

Service and release notices are written to standard error, so standard output and `--json` remain safe for scripts. The CLI never sends command arguments or command output when checking for notices.

## Version and support

Package version: [`0.4.1`](https://github.com/Evokoa/polygres-cli/releases/tag/python-cli-v0.4.1).

Useful commands:

```bash
polygres --version
polygres --help
```

Exit codes distinguish validation (`2`), authentication (`3`), permission (`4`), not found (`5`), conflict (`6`), rate limiting (`7`), service availability (`8`), and missing local tools such as `psql` (`9`).

## CLI and SDK

Install `polygres-cli` for terminal workflows. Install `polygres-sdk` in an application that needs graph, vector, text, or hybrid retrieval. The two packages are independent.

Users of the former combined `polygres` package should install both packages separately when they need both interfaces.

## Changelog

See the [CLI 0.4.1 release notes](https://github.com/Evokoa/polygres-cli/releases/tag/python-cli-v0.4.1) for release changes.
