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
polygres text configs list
```

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
