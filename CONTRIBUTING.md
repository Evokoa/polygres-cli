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

## Publishing

Publishing uses GitHub Actions Trusted Publishing. Validate first through
TestPyPI, then publish a matching `python-cli-vX.Y.Z` tag from the public CLI
repository. Do not add PyPI API tokens to GitHub secrets.

## Scope

This repository contains the public command-line client. Keep control-plane
authentication, configuration, command behavior, and CLI documentation here.
Runtime API retrieval models and library APIs belong in `polygres-sdk`.
