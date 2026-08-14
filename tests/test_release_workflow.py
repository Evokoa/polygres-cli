from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).parents[1]


def _load_release_notes() -> ModuleType:
    path = ROOT / "tools" / "extract_release_notes.py"
    spec = importlib.util.spec_from_file_location("extract_cli_release_notes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE_NOTES = _load_release_notes()


def test_extract_release_notes_returns_only_requested_version() -> None:
    changelog = """# Changelog

## Unreleased

Pending.

## 1.2.3 - 2026-08-12

### Added

- Released feature.

## 1.2.2 - 2026-08-11

- Previous feature.
"""

    notes = RELEASE_NOTES.extract_release_notes(changelog, "1.2.3")

    assert notes == "### Added\n\n- Released feature.\n"


@pytest.mark.parametrize("version", ("1.2", "v1.2.3", "01.2.3", "latest"))
def test_extract_release_notes_rejects_invalid_version(version: str) -> None:
    with pytest.raises(ValueError, match="exact X.Y.Z SemVer form"):
        RELEASE_NOTES.extract_release_notes("", version)


def test_extract_release_notes_requires_one_nonempty_section() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        RELEASE_NOTES.extract_release_notes("# Changelog\n", "1.2.3")

    with pytest.raises(ValueError, match="empty"):
        RELEASE_NOTES.extract_release_notes(
            "# Changelog\n\n## 1.2.3 - 2026-08-12\n\n## 1.2.2 - 2026-08-11\n",
            "1.2.3",
        )


def test_current_changelog_has_release_notes() -> None:
    package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = package["project"]["version"]

    notes = RELEASE_NOTES.extract_release_notes(
        (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version
    )

    assert notes.strip()


def test_publish_workflow_creates_release_after_pypi() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish-python-cli.yml").read_text(
        encoding="utf-8"
    )

    assert "create-github-release:" in workflow
    assert "needs: publish-pypi" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "refs/tags/python-cli-v" in workflow
    assert workflow.count("contents: write") == 1
    assert workflow.count("python tools/extract_release_notes.py") == 2
    assert "gh release create" in workflow
    assert "gh release edit" in workflow
    assert "gh release upload" in workflow
    assert "--clobber" in workflow
    assert "releases/latest" in workflow
