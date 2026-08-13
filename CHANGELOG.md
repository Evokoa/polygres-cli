# Changelog

All notable changes to `polygres-cli` are documented in this file.

## Unreleased

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
