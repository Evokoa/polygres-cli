#!/usr/bin/env python3
"""Verify CLI release-version parity across source, runtime, and an optional tag."""

from __future__ import annotations

import argparse
import re
from importlib.metadata import version
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib

from polygres_cli import __version__

CLI_ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
TAG_PATTERN = re.compile(r"python-cli-v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def source_version() -> str:
    value = str(
        tomllib.loads((CLI_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
            "version"
        ]
    )
    validate_version(value)
    return value


def validate_version(value: str) -> None:
    if VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("CLI release version must use the exact X.Y.Z SemVer form")


def tag_version(tag: str) -> str:
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError("release tag must use the exact python-cli-vX.Y.Z form")
    return tag.removeprefix("python-cli-v")


def verified_versions(tag: str | None = None) -> dict[str, str]:
    expected = {
        "pyproject.toml": source_version(),
        "installed distribution": version("polygres-cli"),
        "runtime export": __version__,
    }
    if tag is not None:
        expected["release tag"] = tag_version(tag)
    for value in expected.values():
        validate_version(value)
    if len(set(expected.values())) != 1:
        raise ValueError(f"CLI release versions do not match: {expected}")
    return expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="optional release tag in python-cli-vX.Y.Z form")
    args = parser.parse_args(argv)
    try:
        versions = verified_versions(args.tag)
    except ValueError as error:
        parser.error(str(error))
    print(f"CLI release version is consistent: {versions['pyproject.toml']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
