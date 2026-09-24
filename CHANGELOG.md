# Changelog

All notable changes to `polygres-cli` are documented in this file.

## Unreleased

## 0.7.0 - 2026-09-24

### Compatibility

- Archived-project failures now exit with code 8 instead of 6. Update scripts
  that branch on exit code 6 for `PROJECT_ARCHIVED`. This public behavior change
  is released as a minor version before 1.0. Status inspection still exits 0.
- Shared-catalog refresh also changes embedding and export error exit codes.
  See the [CLI 0.7.0 migration table](README.md#upgrading-to-cli-070).

### Fixed

- Show Archiving, Archived, and Restoring instead of the provisioning status in
  project lists and status output. Preserve archive state and operation failures
  in JSON status output and provide restoration guidance in human output.
- Report blocked project access with the canonical archive message and exit code
  8. These errors previously fell back to HTTP-conflict exit code 6.
- Refresh bundled API routes, shared error definitions, and contract fixtures.

## 0.6.0 - 2026-09-16

### Added

- Add oversized-failure recovery with preview, confirmation, internal version
  handling, non-interactive approval, and protection against ambiguous replay.
- Add opt-in progress summaries and bounded generation/search-publication watching.

### Changed

- Default new generation setups to automatic oversized-only chunking. Preserve
  legacy payloads, saved settings, vector-copy defaults and existing command output.
- Explain unsupported new features on older servers without silent fallback.
- Document configuration-local parallel batches and recovery semantics.


## 0.5.0 - 2026-09-12

### Added

- Added `polygres embeddings` commands to discover eligible sources, list models
  and usage, preview generation, and create, inspect, update, or remove managed
  embedding configurations.
- Added `run`, `pause`, `resume`, `retry`, and `reconcile` processing controls,
  and `context` handoff for search collection setup.
- Configuration files accept JSON from a file or standard input. Creation
  accepts caller-owned idempotency keys; removal requires an expected
  version and an explicit choice to keep or delete managed output.

- Existing Context search, grouped search, and graph-hybrid commands accept
  `--text` or `--text-file` as alternatives to explicit vectors. `text-hybrid`
  can generate its query embedding from `--query`.
- Select named vectors with `--vector-name`. Text queries support opt-in
  `--use-credits`, stable `--idempotency-key` retries, and `--timeout`.

### Changed

- Embedding commands use scoped Runtime access and a 130-second request timeout.
- Refreshed the bundled API specification and shared contracts for embedding
  models, quotas, generation progress, and provider errors. Context responses
  include HNSW storage limits and structured collection failures when available.

### Compatibility

- Existing vector input flags and result formats remain supported. Text input
  requires an updated Runtime; CLI 0.4.1 cannot submit text-only queries through
  its bundled API request schema.

- Existing command syntax and saved login credentials remain supported. Upgrade
  to 0.5.0 to use `embeddings` or discover its routes through `api request`.
- Managed generation requires embedding services, an enabled model catalog, and
  a quota policy in the connected environment. It must be configured explicitly
  for a source table and stores output separately from source columns.

## 0.4.1 - 2026-08-25

### Changed

- Human-readable durable Context operation failures now include the stable
  error code, failure stage, and operation ID when those recovery fields are
  available.

### Fixed

- Updated the bundled public error catalog for actionable collection sync,
  timeout, connection, memory, storage, and index failures.

## 0.4.0 - 2026-08-19

### Added

- Added one-step `polygres projects create sync <name>` orchestration for source
  inspection, table selection, admission, and project provisioning without
  exposing internal attempt IDs.
- Sync source credentials are accepted only through named environment variables
  or hidden interactive prompts; mutations expose resumable idempotency keys.

### Changed

- Synchronized PostgreSQL projects now reject database connection CLI surfaces
  with the stable `SYNCED_PROJECT_SURFACE_UNAVAILABLE` permission contract
  before any database client is started. Public readiness and vector commands
  remain available.

## 0.3.0 - 2026-08-14

### Added

- Added `polygres rows validate`, `insert`, `upsert`, and `ignore` for one JSON
  object from a file or standard input.
- Added explicit pgContext reconciliation with generated or supplied resume
  keys, default durable-operation waiting, and `--no-wait` support.

### Changed

- Row mutations never automatically retry after authentication, transport, or
  server uncertainty. Ambiguous outcomes use stable exit code 8.

## 0.2.2 - 2026-08-12

### Added

- Added commands to inspect, update, diagnose, rebuild, and remove text-search
  configurations.
- Added one-step TSVector setup for creating a generated column, index, and
  configuration from one or more source columns.

### Changed

- Text-search commands now support compound row keys, metadata and filter
  columns, configured result limits, and both generated and existing TSVector
  columns.

## 0.2.1 - 2026-08-09

### Added

- Added `polygres context init` for reusing eligible pgvector embedding columns
  with pgContext.
- Bundled Runtime API contracts now cover multiple named vectors per Context
  collection.

### Changed

- `polygres vector configs create` now returns a migration error directing users to
  `polygres context collections create`.

### Fixed

- Project status commands now consistently honor the global `--project` option.
- Release validation now supports Python 3.10 through its compatible TOML parser.

## 0.2.0 - 2026-08-08

### Added

- Added `polygres context` commands for configuring, managing, and querying pgContext collections.
- Added `polygres api routes` and `polygres api request` for exploring and calling supported Runtime API routes.
- Added CLI notices for product updates and important service information.
- Added `polygres vector configs set-default <config-id>` for selecting the default vector configuration from the CLI.

### Changed

- Graph status now explains activation failures and configuration differences.
- Graph configuration now uses `id_columns` while remaining compatible with existing `id_column` configurations.

### Fixed

- Graph and vector activation failures now return nonzero exit codes.
- Authentication errors no longer expose internal service details.
- CSV imports now work with destination tables protected by row-level security.

## 0.1.2 - 2026-07-14

### Changed

- CSV imports now upload directly to blob staging for improved reliability.
- CSV upload limits now follow the storage allowance of the selected project tier.

## 0.1.0 - 2026-07-09

### Added

- Initial standalone `polygres-cli` package.
- Added browser authentication, project management, connection information, Runtime API key management, CSV imports, migrations, graph/vector/text configuration, readiness checks, JSON output, and stable exit codes.
