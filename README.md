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

Package version: [`0.7.0`](https://github.com/Evokoa/polygres-cli/releases/tag/python-cli-v0.7.0).

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

See the [CLI 0.7.0 release notes](https://github.com/Evokoa/polygres-cli/releases/tag/python-cli-v0.7.0) for release changes.

## Managed automatic embeddings

CLI 0.7.0 supports managed generation for watched text columns and text queries using
the configuration's pinned model. Managed output is stored separately from source
columns. Upgrade an existing standalone CLI installation with:

```bash
pipx install "polygres-cli==0.7.0" --force
polygres --version
polygres --project PROJECT embeddings --help
polygres --project PROJECT embeddings sources
polygres --project PROJECT embeddings models
polygres --project PROJECT embeddings usage
```

Use `preview --file configuration.json` before `create --file configuration.json`.
Both accept `--file -` for standard input. Inspect progress with `list` and `get ID`;
use `run`, `pause`, `resume`, `retry`, or `reconcile` with the configuration ID to
control processing. `context ID` returns the managed source for separate Context
collection setup. Query the collection with existing Context commands:

```bash
polygres context search articles --text "How does replication work?" --vector-name content
polygres context search articles --embedding-file query-vector.json
```

Supply `--idempotency-key KEY` to creation and search when a request may need to
resume after an interrupted response. `update ID --file changes.json` requires
`expected_version` in the JSON body. `remove ID --expected-version VERSION`
requires exactly one of `--keep-output` or `--delete-output`. Context text queries
preserve existing filters and ranking options. Use `--text-file PATH` (or `-` for
stdin), opt into authorized credits with `--use-credits`, and set a request
deadline with `--timeout SECONDS`. `text-hybrid` can generate an embedding from
its existing `--query` argument. Explicit-vector calls remain supported.

Existing commands and saved login credentials remain supported. Availability
requires embedding services, an enabled model catalog, and a quota policy in the
connected environment. See the [automatic embeddings guide](https://docs.polygres.com/platform/automatic-embeddings)
for configuration fields, quotas, and recovery.

## Automatic chunking and selective recovery (CLI 0.7.0)

New generation configurations default to `"chunking": {"mode": "automatic"}`.
Documents that fit the selected model remain whole. Oversized documents split at
its token limit, allowing for model prefixes and overlap. Initial generation and
later text/CDC changes use the same policy. `custom` and `off` remain available.
Legacy `enabled`/size/overlap payloads and saved configurations retain their meaning.
Existing-vector copying retains its unchunked default. Queries are not automatically
chunked; shorten an oversized query.

```bash
polygres --project PROJECT embeddings recover-oversized CONFIGURATION --preview
polygres --project PROJECT embeddings recover-oversized CONFIGURATION
polygres --json --project PROJECT embeddings recover-oversized CONFIGURATION --yes
polygres --project PROJECT embeddings get CONFIGURATION --summary
polygres --project PROJECT embeddings list --summary
polygres --json --project PROJECT embeddings get CONFIGURATION --watch --timeout 600
```

Recovery previews eligible and blocked failures, model limits and sample chunk
counts. Confirmation enables automatic chunking for future source updates and
requeues eligible failures. The command handles configuration versions internally.
Successful documents and unknown provider outcomes stay untouched. A paused
configuration stays paused. Rows are checked again on submission, so the final
queued count can differ from the preview. Queued work is not completed generation.
If there are no eligible rows, no settings change is submitted.

Interactive recovery confirms the displayed changes. A configuration conflict
refreshes the preview and asks again, at most three submissions. JSON and other
non-interactive execution require `--yes` to mutate; `--preview` never mutates.
Scripts exit on a version conflict. An ambiguous submission is never blindly
repeated: inspect configuration progress and a fresh preview before deciding to retry.

Existing commands retain their JSON output and syntax. `--summary` opts into a
readable view on get/list/preview/create and processing actions; `--json` takes
precedence. `get --watch` polls without mutation until generation and search
publication finish. It stops on timeout, interruption, or generation requiring
user action. It does not resume paused work. In JSON mode it prints one final
configuration or a structured error, not a stream of concatenated JSON values.
Missing progress fields are reported as unknown, not zero.

Batches stay within one configuration, with up to four concurrent provider calls
subject to shared worker limits. Pause stops new admission while started calls
can finish. Retry preserves saved results and does not enable chunking. Reconcile
does not authorize repeating unknown provider consumption. Search indexing and
usage acknowledgements are separate from generation progress. Batch and worker
settings are operator-managed and have no CLI tuning flags.

An older server can still accept explicit off/custom chunking in legacy format.
Automatic chunking and selective recovery require a compatible backend. Precise
unsupported-field/action responses produce an upgrade message without silently
disabling chunking or substituting an ordinary retry. Existing login/config files
and JSON response fields remain compatible.

## Archived projects

`polygres projects list` and `polygres projects status` display **Archiving**,
**Archived**, or **Restoring** instead of the provisioning status while access
is blocked. JSON output preserves the underlying provisioning `status` and the
separate `archive_state`. Status output also includes the latest archive
operation when available, including archive/restore failures and request IDs.

Blocked database commands return `PROJECT_ARCHIVED`, HTTP 409, and exit code
**8**. CLI 0.6.0 used fallback conflict exit code 6 for this error; scripts should
accept the corrected code when upgrading. Messages explain whether the project
is being archived, needs restoration in the dashboard, or is being restored.
Commands do not automatically restore projects. Inspecting project status still
exits successfully with code 0.

## Upgrading to CLI 0.7.0

Command syntax remains supported. Update scripts that branch on these error
exit codes, corrected by the shared-catalog refresh:

| Error code | CLI 0.6.0 | CLI 0.7.0 |
| --- | --- | --- |
| `EMBEDDING_CONNECTION_CONFLICT` | 2 | 4 |
| `EMBEDDING_MODEL_PROBE_REQUIRED` | 2 | 4 |
| `EMBEDDING_TOKENIZER_UNAVAILABLE` | 2 | 4 |
| `PROJECT_ARCHIVED` | 6 | 8 |
| `PROJECT_ARCHIVE_CONFLICT` | 6 | 8 |
| `PROJECT_ARCHIVE_UNSUPPORTED` | 6 | 8 |
| `PROJECT_EXPORT_EXPIRED` | 2 | 8 |
| `PROJECT_EXPORT_NOT_FOUND` | 5 | 8 |
| `PROJECT_EXPORT_NOT_READY` | 6 | 8 |
| `PROJECT_EXPORT_NOT_SUPPORTED` | 6 | 8 |

The updated Runtime backend returns authenticated archived-project failures as
HTTP 409 `PROJECT_ARCHIVED` instead of HTTP 404 `RUNTIME_PROJECT_NOT_FOUND`.
Even without upgrading the CLI, that Runtime response change moves the released
CLI 0.6.0 fallback exit code from 5 to 6. Central API archive denials already
use HTTP 409. Older CLI versions can still make existing requests, but do not
provide the corrected archive status display.
