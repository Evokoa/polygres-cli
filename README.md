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

## Version and support

The current published CLI release is [`0.1.2`](https://github.com/Evokoa/polygres-cli/releases/tag/python-cli-v0.1.2).

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

See the [CLI 0.1.2 release notes](https://github.com/Evokoa/polygres-cli/releases/tag/python-cli-v0.1.2) for published changes.
