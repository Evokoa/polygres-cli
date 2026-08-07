# Changelog

All notable changes to `polygres-cli` are documented in this file.

## 0.2.0 - 2026-08-06

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
- Project status commands now consistently honor the global `--project` option.

## 0.1.2 - 2026-07-14

### Changed

- CSV imports now upload directly to blob staging for improved reliability.
- CSV upload limits now follow the storage allowance of the selected project tier.

## 0.1.0 - 2026-07-09

### Added

- Initial standalone `polygres-cli` package.
- Added browser authentication, project management, connection information, Runtime API key management, CSV imports, migrations, graph/vector/text configuration, readiness checks, JSON output, and stable exit codes.
