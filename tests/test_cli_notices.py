from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx

from polygres_cli import __version__, cli
from polygres_cli.cli_notices import NoticeManager, parse_semver, sanitize_text

API_BASE_URL = "https://api.example.test/v1"
NOTICE_URL = f"{API_BASE_URL}/cli/notices"
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
ROUTE_CTX = getattr(respx, "mo" + "ck")


def _notice(notice_id: str = "notice-1", **overrides: object) -> dict[str, object]:
    return {
        "id": notice_id,
        "severity": "info",
        "title": "Service update",
        "message": "A service update is available.",
        "url": "https://docs.polygres.com/cli",
        "start_at": None,
        "expires_at": None,
        "min_cli_version": None,
        "max_cli_version": None,
        "display_policy": "once",
        "release_channels": [],
        "operating_systems": [],
        "architectures": [],
        **overrides,
    }


def _client(payload: object, calls: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json=payload,
            headers={
                "ETag": '"notice-etag"',
                "Cache-Control": "public, max-age=36000, must-revalidate",
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def _manager(
    tmp_path: Path,
    payload: object,
    calls: list[httpx.Request],
    now: list[datetime],
) -> NoticeManager:
    return NoticeManager(
        base_url=API_BASE_URL,
        cli_version="0.2.0",
        state_path=tmp_path / "notices.json",
        client=_client(payload, calls),
        now=lambda: now[0],
        channel="stable",
        operating_system="macos",
        architecture="arm64",
    )


def test_notice_response_is_cached_for_ten_hours(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    now = [NOW]
    manager = _manager(tmp_path, {"notices": [_notice()]}, calls, now)

    manager.display()
    now[0] += timedelta(hours=9, minutes=59)
    manager.display()

    assert len(calls) == 1
    assert calls[0].url.params["version"] == "0.2.0"
    assert calls[0].url.params["channel"] == "stable"
    state = json.loads((tmp_path / "notices.json").read_text())
    assert state["cache"]["max_age_seconds"] == 36000
    assert state["cache"]["etag"] == '"notice-etag"'


def test_once_daily_and_always_display_policies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[httpx.Request] = []
    now = [NOW]
    manager = _manager(
        tmp_path,
        {
            "notices": [
                _notice("once", display_policy="once"),
                _notice("daily", display_policy="daily"),
                _notice("always", display_policy="always"),
            ]
        },
        calls,
        now,
    )

    manager.display()
    first = capsys.readouterr().err
    manager.display()
    second = capsys.readouterr().err
    now[0] += timedelta(hours=25)
    manager.display()
    third = capsys.readouterr().err

    assert "[INFO] Service update" in first
    assert first.count("Service update") == 3
    assert second.count("Service update") == 1
    assert third.count("Service update") == 2


def test_filters_version_window_and_platform_targets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[httpx.Request] = []
    now = [NOW]
    manager = _manager(
        tmp_path,
        {
            "notices": [
                _notice("matching", min_cli_version="0.1.0", max_cli_version="0.2.0"),
                _notice("future-version", min_cli_version="0.3.0"),
                _notice("expired", expires_at="2026-07-31T11:59:59Z"),
                _notice("future-window", start_at="2026-08-01T00:00:00Z"),
                _notice("wrong-channel", release_channels=["beta"]),
                _notice("wrong-os", operating_systems=["linux"]),
                _notice("wrong-arch", architectures=["amd64"]),
            ]
        },
        calls,
        now,
    )

    displayed = manager.display()

    assert [notice.id for notice in displayed] == ["matching"]
    assert capsys.readouterr().err.count("Service update") == 1


def test_sanitizes_text_and_drops_invalid_links(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[httpx.Request] = []
    now = [NOW]
    manager = _manager(
        tmp_path,
        {
            "notices": [
                _notice(
                    title="\x1b[31mCritical\x1b[0m\nTitle",
                    message="Message\x00\u202e hidden",
                    url="https://user:password@example.com/path",
                )
            ]
        },
        calls,
        now,
    )

    manager.display()
    output = capsys.readouterr().err

    assert "\x1b" not in output
    assert "\x00" not in output
    assert "\u202e" not in output
    assert "Critical Title" in output
    assert "More information" not in output
    assert len(sanitize_text("x" * 2000, limit=1000)) == 1000


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"notices": "wrong"},
        {"notices": [_notice(severity="debug")]},
        {"notices": [_notice(), _notice()]},
        {"notices": [_notice(min_cli_version="not-semver")]},
        {"notices": [_notice()], "remote_handler": "run"},
    ],
)
def test_malformed_responses_fail_silently(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    payload: object,
) -> None:
    calls: list[httpx.Request] = []
    manager = _manager(tmp_path, payload, calls, [NOW])

    displayed = manager.display()

    assert displayed == []
    assert capsys.readouterr().err == ""


def test_force_refresh_uses_etag_and_304_cache(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={"notices": [_notice()]}, headers={"ETag": '"v1"'})
        return httpx.Response(304, headers={"ETag": '"v1"', "Cache-Control": "max-age=36000"})

    manager = NoticeManager(
        base_url=API_BASE_URL,
        cli_version="0.2.0",
        state_path=tmp_path / "notices.json",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: NOW,
    )

    manager.display()
    manager.display(force_refresh=True, ignore_display_policy=True)

    assert len(requests) == 2
    assert requests[1].headers["If-None-Match"] == '"v1"'


def test_timeout_and_offline_cache_failure_do_not_raise(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("offline")

    manager = NoticeManager(
        base_url=API_BASE_URL,
        cli_version="0.2.0",
        state_path=tmp_path / "notices.json",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert manager.display(force_refresh=True) == []


def test_expired_cache_is_not_displayed_while_offline(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    now = [NOW]
    initial = _manager(tmp_path, {"notices": [_notice(display_policy="always")]}, calls, now)
    assert initial.display()

    def offline(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    now[0] += timedelta(hours=11)
    manager = NoticeManager(
        base_url=API_BASE_URL,
        cli_version="0.2.0",
        state_path=tmp_path / "notices.json",
        client=httpx.Client(transport=httpx.MockTransport(offline)),
        now=lambda: now[0],
    )

    assert manager.display() == []


def test_rejects_untrusted_non_https_api_origin(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid configured Polygres API origin"):
        NoticeManager(
            base_url="http://attacker.example/v1",
            cli_version="0.2.0",
            state_path=tmp_path / "notices.json",
        )


@ROUTE_CTX
def test_post_command_notice_uses_stderr_without_corrupting_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("POLYGRES_API_BASE_URL", API_BASE_URL)
    respx.get(NOTICE_URL).mock(return_value=httpx.Response(200, json={"notices": [_notice()]}))

    result = cli.main(["--json", "api", "routes"])
    captured = capsys.readouterr()

    assert result == 0
    assert json.loads(captured.out)["routes"]
    assert "[INFO] Service update" in captured.err


@ROUTE_CTX
def test_version_forces_refresh_and_offline_failure_is_silent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("POLYGRES_API_BASE_URL", API_BASE_URL)
    route = respx.get(NOTICE_URL).mock(side_effect=httpx.ReadTimeout("timed out"))

    result = cli.main(["--version"])
    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == f"polygres {__version__}\n"
    assert captured.err == ""
    assert route.called


@ROUTE_CTX
def test_notices_command_refreshes_and_displays_regardless_of_once_policy(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("POLYGRES_API_BASE_URL", API_BASE_URL)
    respx.get(NOTICE_URL).mock(return_value=httpx.Response(200, json={"notices": [_notice()]}))

    first = cli.main(["--json", "notices"])
    first_capture = capsys.readouterr()
    second = cli.main(["--json", "notices"])
    second_capture = capsys.readouterr()

    assert first == second == 0
    assert first_capture.out == second_capture.out == ""
    assert "[INFO] Service update" in first_capture.err
    assert "[INFO] Service update" in second_capture.err


def test_semver_comparison_accepts_prereleases() -> None:
    assert parse_semver("0.2.0-rc.1") is not None
    assert parse_semver("0.2") is None
