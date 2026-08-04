# Changelog

All notable changes to `polygres-cli` are documented in this file.

## 0.2.0 - 2026-07-31

### Added

- Added the complete `polygres context` namespace for pgContext capabilities,
  discovery, preflight, collection lifecycle, filters, points, durable
  operations, aggregates, dense retrieval, text hybrid, graph composition,
  rank fusion, coupled Joint retrieval, grouping, and recall checks.
- Added strict shared-contract validation, file and standard-input request
  handling, mutation idempotency, adaptive durable-operation waiting, exact
  JSON envelopes, and Context-specific human output.
- Added `polygres api routes` and `polygres api request` with a bundled,
  versioned OpenAPI snapshot, strict route and method selection, declared
  parameters, JSON-schema body validation, schema inspection, dry runs, and
  JSON output.
- Added FastAPI schema generation and drift validation for the bundled CLI
  OpenAPI snapshot.
- Added server-controlled CLI notices with a public API endpoint, 10-hour local
  cache, ETag revalidation, version and platform targeting, safe plain-text
  stderr rendering, `once`/`daily`/`always` display policies, and the static
  `polygres notices` command.
- Added `polygres vector configs set-default <config-id>` for selecting the
  default vector configuration without using the web console.
- Added direct Runtime API graph access support for graph discovery,
  configuration, builds, and status checks when
  `CLI_DIRECT_RUNTIME_GRAPH_ENABLED` is enabled and the control plane grants
  access.

### Changed

- Graph status output now includes activation failure reasons and a concise
  summary of configuration differences.
- Graph configuration export and apply flows now canonicalize table identifiers
  as `id_columns`, while continuing to accept legacy `id_column` input.
- Authentication contracts are vendored into the package so standalone CLI
  exports do not depend on an external `polygres-lib` installation.

### Fixed

- Graph and vector activation verification failures now return nonzero CLI exit
  codes instead of appearing successful to automation.
- Authentication errors no longer expose internal identity-provider details.

## 0.1.2 - 2026-07-14

### Changed

- CSV imports now upload directly to blob staging for improved reliability.
- CSV upload limits now follow the storage allowance of the selected project
  tier.

## 0.1.1 - 2026-07-14

### Changed

- Added Python 3.10 to release validation for the standalone CLI package.

## 0.1.0 - 2026-07-09

### Added

- Initial standalone `polygres-cli` package.
- Added browser authentication, project management, connection information,
  Runtime API key management, CSV imports, migrations, graph/vector/text
  configuration, readiness checks, JSON output, and stable exit codes.
