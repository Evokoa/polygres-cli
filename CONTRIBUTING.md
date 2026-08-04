# Contributing

## Development setup

Use Python 3.10 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

```bash
pytest
ruff check .
python -m build
```

## OpenAPI snapshot

The generic `polygres api` surface reads
`src/polygres_cli/openapi/control-plane-v1.json`. Generate it from the
monorepo's FastAPI application after changing routes or schemas:

```bash
python packages/python-cli/tools/generate_openapi_snapshot.py
python packages/python-cli/tools/generate_openapi_snapshot.py --check
```

Run these commands from the monorepo root in an environment containing the
`services/api` dependencies. The API test suite compares the committed
snapshot with `create_app().openapi()`, while the CLI tests validate the
bundled resource and request behavior.

The public `GET /v1/cli/notices` operation is part of that snapshot. Any notice
response-schema or targeting change therefore requires regenerating the
snapshot and running both the API and CLI notice tests. Publishing notice rows
does not require regenerating the snapshot or releasing the CLI. See
`services/api/CLI_NOTICES.md` in the monorepo for the operational workflow.

## Publishing

Publishing uses GitHub Actions Trusted Publishing. Validate first through
TestPyPI, then publish a matching `python-cli-vX.Y.Z` tag from the public CLI
repository. Do not add PyPI API tokens to GitHub secrets.

Before syncing a release to the public CLI repository:

1. Add the release notes and date to `CHANGELOG.md`.
2. Update the version in `pyproject.toml` and
   `src/polygres_cli/cli_client.py`.
3. Update version assertions in the test suite and public installation
   documentation.
4. Run `pytest`, `ruff check .`, `python -m build`, and
   `python -m twine check dist/*`.
5. Validate the release through TestPyPI before creating the matching
   production tag.

## Scope

This repository contains the public command-line client. Keep control-plane
authentication, configuration, command behavior, and CLI documentation here.
Runtime API retrieval models and library APIs belong in `polygres-sdk`.
