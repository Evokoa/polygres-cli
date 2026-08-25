from __future__ import annotations

import importlib.util
import runpy
from importlib.metadata import version
from pathlib import Path
from types import ModuleType

import pytest

from polygres_cli import __version__


def _load_verifier() -> ModuleType:
    path = Path(__file__).parents[1] / "tools" / "verify_release_version.py"
    spec = importlib.util.spec_from_file_location("verify_cli_release_version", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = _load_verifier()


def test_runtime_version_matches_installed_distribution() -> None:
    assert __version__ == version("polygres-cli")
    assert __version__ != "0+unknown"


def test_source_import_has_explicit_unknown_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata

    version_file = Path(__file__).parents[1] / "src" / "polygres_cli" / "_version.py"

    def missing_distribution(_: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing_distribution)
    namespace = runpy.run_path(str(version_file))

    assert namespace["__version__"] == "0+unknown"


def test_release_versions_match_current_distribution() -> None:
    expected = VERIFIER.source_version()
    values = VERIFIER.verified_versions(f"python-cli-v{expected}")

    assert set(values.values()) == {expected}


def test_release_documentation_names_current_cli_version() -> None:
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "Package version: [`0.4.1`]" in readme
    assert "python-cli-v0.4.1" in readme
    assert "CLI 0.4.1 release notes" in readme
    assert "## 0.4.1 - 2026-08-25" in changelog


@pytest.mark.parametrize(
    "tag",
    (
        "python-cli-v0.2",
        "python-cli-v0.2.0-rc.1",
        "python-cli-v0.2.0-extra!",
        "python-cli-v00.2.0",
        "python-cli-vbanana",
        "polygres-cli-v0.2.0",
    ),
)
def test_release_tag_requires_exact_semver_shape(tag: str) -> None:
    with pytest.raises(ValueError, match="exact python-cli-vX.Y.Z form"):
        VERIFIER.tag_version(tag)


def test_release_tag_must_match_distribution() -> None:
    with pytest.raises(ValueError, match="do not match"):
        VERIFIER.verified_versions("python-cli-v0.2.1")
