from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from polygres_cli import __version__

pytestmark = pytest.mark.heavy


def test_installed_cli_staging_whoami_contract(tmp_path: Path) -> None:
    """Opt-in smoke for an installed wheel and a disposable staging token."""
    executable = os.environ.get("POLYGRES_HEAVY_CLI")
    api_base_url = os.environ.get("POLYGRES_HEAVY_API_BASE_URL")
    access_token = os.environ.get("POLYGRES_HEAVY_ACCESS_TOKEN")
    if not executable or not api_base_url or not access_token:
        pytest.skip(
            "set POLYGRES_HEAVY_CLI, POLYGRES_HEAVY_API_BASE_URL, and "
            "POLYGRES_HEAVY_ACCESS_TOKEN"
        )

    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "POLYGRES_API_BASE_URL": api_base_url,
        "POLYGRES_ACCESS_TOKEN": access_token,
    }
    version = subprocess.run(
        [executable, "--version"], env=env, text=True, capture_output=True, check=False
    )
    assert version.returncode == 0
    assert version.stdout.strip() == f"polygres {__version__}"

    notices = subprocess.run(
        [executable, "--json", "notices"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert notices.returncode == 0, notices.stderr
    assert notices.stdout == ""
    assert "No active CLI notices." in notices.stderr or any(
        label in notices.stderr for label in ("[INFO]", "[WARNING]", "[CRITICAL]")
    )

    whoami = subprocess.run(
        [executable, "--json", "whoami"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert whoami.returncode == 0, whoami.stderr
    payload = json.loads(whoami.stdout)
    assert payload["profile"]["id"]
    assert payload["profile"]["email"]
    assert payload["organization"]["id"]
    assert payload["membership"]["status"] == "active"
    assert "access_token" not in whoami.stdout
    assert "refresh_token" not in whoami.stdout
    assert "No active CLI notices." not in whoami.stdout
    assert not any(
        label in whoami.stdout for label in ("[INFO]", "[WARNING]", "[CRITICAL]")
    )
