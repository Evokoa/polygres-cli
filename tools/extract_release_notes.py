#!/usr/bin/env python3
"""Extract one version's Markdown section from the package changelog."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def extract_release_notes(changelog: str, version: str) -> str:
    if VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("release version must use the exact X.Y.Z SemVer form")

    lines = changelog.splitlines()
    heading_pattern = re.compile(rf"^## {re.escape(version)}(?:\s+-\s+.+)?\s*$")
    headings = [index for index, line in enumerate(lines) if heading_pattern.fullmatch(line)]
    if len(headings) != 1:
        raise ValueError(
            f"CHANGELOG.md must contain exactly one level-two heading for version {version}"
        )

    start = headings[0] + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    notes = "\n".join(lines[start:end]).strip()
    if not notes:
        raise ValueError(f"CHANGELOG.md release notes for version {version} are empty")
    return f"{notes}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="release version in X.Y.Z form")
    parser.add_argument(
        "--changelog",
        type=Path,
        default=PACKAGE_ROOT / "CHANGELOG.md",
        help="path to the changelog",
    )
    parser.add_argument("--output", type=Path, required=True, help="release-notes output path")
    args = parser.parse_args(argv)
    try:
        notes = extract_release_notes(args.changelog.read_text(encoding="utf-8"), args.version)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.write_text(notes, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
