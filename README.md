# Polygres CLI

The Polygres CLI manages Polygres projects from the terminal. It authenticates
with the control plane and supports project setup, imports, migrations, and
retrieval configuration. It does not expose database passwords.

## Install

```bash
pip install polygres-cli
```

For an isolated global installation:

```bash
pipx install polygres-cli
```

From the repository root, create an isolated development environment and
install the CLI in editable mode:

```bash
python3 -m venv .venv
source .venv/bin/activate
sfw pip install -e packages/python-cli
polygres context capabilities --help
```

The command remains `polygres`:

```bash
polygres login
polygres whoami
polygres projects list
polygres projects use <project-id-or-exact-name>
polygres env
polygres ready
```

`polygres login` opens the Polygres dashboard for approval and prints a URL for
headless terminals. Credentials are stored at
`~/.config/polygres/config.json` with owner-only permissions on POSIX systems.
Run `polygres logout` to revoke the refresh token and remove local credentials.

Common project operations:

```bash
polygres import csv ./documents.csv --table documents --wait
polygres migrations apply --file ./001_create_documents.sql
polygres graph discover --json > graph.json
polygres graph config apply --file graph.json
polygres vector configs list
polygres vector configs set-default <config-id>
polygres text configs list
polygres context capabilities
polygres context collections list
polygres api routes
polygres notices
```

AI Search commands use the existing login and selected-project workflow:

```bash
polygres login
polygres projects use <project-id-or-exact-name>
polygres context sources discover
polygres context collections create support_docs \
  --source new-table \
  --table support_docs \
  --dimensions 768
polygres context search support_docs --embedding-file query-embedding.json
polygres context joint support_docs \
  --embedding-file query-embedding.json \
  --query "current guidance" \
  --semantic-weight 0.6 \
  --lexical-weight 0.1 \
  --graph-weight 0.3
```

Context is the pgContext-backed collection namespace. It does not reuse
pgvector configurations. Mutations send an idempotency key and wait for their
durable operation by default; use `--no-wait` to return after acceptance.
Global `--json`, `--project`, `--quiet`, and `--verbose` flags must precede
`context`.

## Generic API routes

The `api` namespace exposes control-plane routes from the versioned OpenAPI
snapshot bundled with the CLI. It supplements the stable high-level commands;
those commands and their handlers remain registered in Python.

List routes, inspect one operation, validate a dry run, and execute it:

```bash
polygres api routes
polygres --json api routes --method GET
polygres --json api request /projects/{project_id} --method GET --schema
polygres --json --project <project-id> api request /projects/{project_id} \
  --method GET \
  --dry-run
polygres --json api request /projects \
  --method POST \
  --body '{"name":"Support Search"}'
```

Use repeatable `--param NAME=VALUE` options for declared path and query
parameters. Prefix an ambiguous name with `path:`, `query:`, or `header:`.
Use `--body-file <path>` for a UTF-8 JSON document, or `--body-file -` to read
one from standard input.

Only route templates and HTTP methods in the bundled snapshot can execute.
Full URLs, query strings in the route argument, undeclared parameters,
unsupported methods, unsafe path values, and bodies that do not satisfy the
declared JSON schema are rejected before a request is sent.

## CLI notices

After a command succeeds, the CLI checks the configured Polygres API for
applicable service and release notices. Notice text is written only to standard
error, so standard output and `--json` remain safe for automation. The response
is cached for up to 10 hours at `~/.config/polygres/notices.json`. Running
`polygres --version` forces a conditional refresh, and `polygres notices`
refreshes and displays all currently applicable notices regardless of their
normal `once` or `daily` display policy.

The check uses a two-second timeout and never changes a command's exit status.
Network failures, offline operation, malformed responses, and an unavailable
notice service are silent. Requests go only to the fixed `/cli/notices` path at
the configured Polygres API origin. The CLI sends its version, derived release
channel, operating system, and architecture for targeting. It does not send
command arguments or command output.

Remote notices are plain text. The CLI strips control and ANSI characters,
limits title and message lengths, accepts only validated HTTPS links, and uses
a fixed local renderer. Notices cannot define commands, handlers, formatting,
or endpoints.

Run `polygres --help` for the full command reference. Exit codes distinguish
validation (`2`), authentication (`3`), permission (`4`), not found (`5`),
conflict (`6`), rate limiting (`7`), remote availability (`8`), and missing
local tools such as `psql` (`9`).

## Relationship to the Python SDK

The CLI is distributed separately from the Python SDK. Install `polygres-sdk` when
your application needs Runtime API retrieval methods, and install
`polygres-cli` when you need the terminal command. The CLI has its own
control-plane client and does not require the SDK.

Users of the former combined `polygres` package should install `polygres-cli`
and `polygres-sdk` separately.

See [CHANGELOG.md](CHANGELOG.md) for release notes.
