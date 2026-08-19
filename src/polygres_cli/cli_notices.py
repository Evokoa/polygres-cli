from __future__ import annotations

import json
import os
import platform
import re
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

import httpx

CACHE_TTL = timedelta(hours=10)
DAILY_INTERVAL = timedelta(hours=24)
NOTICE_TIMEOUT_SECONDS = 2.0
STATE_VERSION = 1
MAX_TITLE_LENGTH = 120
MAX_MESSAGE_LENGTH = 1000
MAX_URL_LENGTH = 2048
MAX_NOTICE_ID_LENGTH = 128
MAX_RESPONSE_BYTES = 256 * 1024
_NOTICE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
_SEMVER = re.compile(
    r"^(?:v)?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_ANSI_ESCAPE = re.compile(r"(?:\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?)")


@dataclass(frozen=True, slots=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Notice:
    id: str
    severity: str
    title: str
    message: str
    url: str | None
    start_at: datetime | None
    expires_at: datetime | None
    min_cli_version: SemanticVersion | None
    max_cli_version: SemanticVersion | None
    display_policy: str
    release_channels: tuple[str, ...]
    operating_systems: tuple[str, ...]
    architectures: tuple[str, ...]


def default_notice_state_path() -> Path:
    return Path.home() / ".config" / "polygres" / "notices.json"


def release_channel(version: str) -> str:
    parsed = parse_semver(version)
    if parsed is None or not parsed.prerelease:
        return "stable"
    first = parsed.prerelease[0].lower()
    if first.startswith("rc"):
        return "rc"
    if first.startswith("beta") or first.startswith("b"):
        return "beta"
    if first.startswith("alpha") or first.startswith("a"):
        return "alpha"
    return "preview"


def normalized_operating_system() -> str:
    value = platform.system().lower()
    return {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(value, value)


def normalized_architecture() -> str:
    value = platform.machine().lower()
    return {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(value, value)


def parse_semver(value: str) -> SemanticVersion | None:
    match = _SEMVER.fullmatch(value.strip())
    if match is None:
        return None
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
    for identifier in prerelease:
        if identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0"):
            return None
    return SemanticVersion(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prerelease=prerelease,
    )


def compare_semver(left: SemanticVersion, right: SemanticVersion) -> int:
    left_core = (left.major, left.minor, left.patch)
    right_core = (right.major, right.minor, right.patch)
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    if left.prerelease == right.prerelease:
        return 0
    if not left.prerelease:
        return 1
    if not right.prerelease:
        return -1
    for left_part, right_part in zip(left.prerelease, right.prerelease, strict=False):
        if left_part == right_part:
            continue
        left_numeric = left_part.isdigit()
        right_numeric = right_part.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_part) < int(right_part) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_part < right_part else 1
    return -1 if len(left.prerelease) < len(right.prerelease) else 1


def sanitize_text(value: str, *, limit: int) -> str:
    value = _ANSI_ESCAPE.sub("", value)
    value = "".join(
        " " if unicodedata.category(character) in {"Cc", "Cf"} else character for character in value
    )
    return " ".join(value.split())[:limit].strip()


def validated_https_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_URL_LENGTH:
        return None
    if sanitize_text(value, limit=MAX_URL_LENGTH) != value:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    return value


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid notice timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("notice timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _string_targets(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("invalid notice target list")
    targets: list[str] = []
    for item in value:
        if not isinstance(item, str) or not re.fullmatch(r"[a-z0-9_-]{1,32}", item):
            raise ValueError("invalid notice target")
        targets.append(item)
    return tuple(targets)


def parse_notice(value: object) -> Notice:
    if not isinstance(value, dict):
        raise ValueError("notice is not an object")
    notice_id = value.get("id")
    severity = value.get("severity")
    title = value.get("title")
    message = value.get("message")
    display_policy = value.get("display_policy")
    if (
        not isinstance(notice_id, str)
        or len(notice_id) > MAX_NOTICE_ID_LENGTH
        or _NOTICE_ID.fullmatch(notice_id) is None
        or severity not in {"info", "warning", "critical"}
        or not isinstance(title, str)
        or not isinstance(message, str)
        or display_policy not in {"once", "daily", "always"}
    ):
        raise ValueError("notice has invalid required fields")
    clean_title = sanitize_text(title, limit=MAX_TITLE_LENGTH)
    clean_message = sanitize_text(message, limit=MAX_MESSAGE_LENGTH)
    if not clean_title or not clean_message:
        raise ValueError("notice text is empty")
    min_version_value = value.get("min_cli_version")
    max_version_value = value.get("max_cli_version")
    min_version = parse_semver(min_version_value) if isinstance(min_version_value, str) else None
    max_version = parse_semver(max_version_value) if isinstance(max_version_value, str) else None
    if (min_version_value is not None and min_version is None) or (
        max_version_value is not None and max_version is None
    ):
        raise ValueError("notice has an invalid version range")
    if min_version and max_version and compare_semver(min_version, max_version) > 0:
        raise ValueError("notice version range is reversed")
    start_at = _parse_datetime(value.get("start_at"))
    expires_at = _parse_datetime(value.get("expires_at"))
    if start_at and expires_at and start_at >= expires_at:
        raise ValueError("notice active window is invalid")
    return Notice(
        id=notice_id,
        severity=severity,
        title=clean_title,
        message=clean_message,
        url=validated_https_url(value.get("url")),
        start_at=start_at,
        expires_at=expires_at,
        min_cli_version=min_version,
        max_cli_version=max_version,
        display_policy=display_policy,
        release_channels=_string_targets(value.get("release_channels")),
        operating_systems=_string_targets(value.get("operating_systems")),
        architectures=_string_targets(value.get("architectures")),
    )


def _notice_endpoint(base_url: str) -> str:
    parsed = urlsplit(base_url)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        parsed.scheme not in ({"http", "https"} if loopback else {"https"})
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid configured Polygres API origin")
    base_path = parsed.path.rstrip("/")
    return parsed._replace(path=f"{base_path}/cli/notices", query="", fragment="").geturl()


class NoticeManager:
    def __init__(
        self,
        *,
        base_url: str,
        cli_version: str,
        state_path: Path | None = None,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
        channel: str | None = None,
        operating_system: str | None = None,
        architecture: str | None = None,
    ) -> None:
        self._endpoint = _notice_endpoint(base_url)
        self._cli_version_text = cli_version
        parsed_version = parse_semver(cli_version)
        if parsed_version is None:
            raise ValueError("invalid CLI version")
        self._cli_version = parsed_version
        self._state_path = state_path or default_notice_state_path()
        self._client = client
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._channel = channel or release_channel(cli_version)
        self._operating_system = operating_system or normalized_operating_system()
        self._architecture = architecture or normalized_architecture()

    def display(
        self,
        *,
        force_refresh: bool = False,
        ignore_display_policy: bool = False,
        show_empty: bool = False,
        stream: TextIO | None = None,
    ) -> list[Notice]:
        stream = stream or sys.stderr
        now = self._now().astimezone(timezone.utc)
        state = self._load_state()
        payload = self._payload(state, now=now, force_refresh=force_refresh)
        try:
            notices = self._parse_payload(payload)
        except (ValueError, TypeError):
            return []
        displayed = state.setdefault("displayed", {})
        if not isinstance(displayed, dict):
            displayed = {}
            state["displayed"] = displayed
        applicable = [notice for notice in notices if self._is_applicable(notice, now)]
        selected = [
            notice
            for notice in applicable
            if ignore_display_policy or self._display_due(notice, displayed, now)
        ]
        for notice in selected:
            stream.write(self._render(notice))
            displayed[notice.id] = now.isoformat().replace("+00:00", "Z")
        if show_empty and not selected:
            stream.write("No active CLI notices.\n")
        if selected:
            self._save_state(state)
        return selected

    def _payload(self, state: dict[str, Any], *, now: datetime, force_refresh: bool) -> object:
        cached = state.get("cache")
        cached = cached if isinstance(cached, dict) else None
        cache_is_fresh = self._cache_is_fresh(cached, now)
        if not force_refresh and cache_is_fresh:
            return cached.get("payload") if cached else None
        refreshed = self._refresh(cached, now)
        if refreshed is not None:
            state["cache"] = refreshed
            self._save_state(state)
            return refreshed.get("payload")
        return cached.get("payload") if cached and cache_is_fresh else None

    @staticmethod
    def _cache_is_fresh(cached: dict[str, Any] | None, now: datetime) -> bool:
        if cached is None:
            return False
        fetched_at = NoticeManager._safe_timestamp(cached.get("fetched_at"))
        max_age = cached.get("max_age_seconds", int(CACHE_TTL.total_seconds()))
        return bool(
            fetched_at is not None
            and isinstance(max_age, int)
            and not isinstance(max_age, bool)
            and 0 <= max_age <= int(CACHE_TTL.total_seconds())
            and now - fetched_at < timedelta(seconds=max_age)
        )

    def _refresh(self, cached: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"polygres-cli/{self._cli_version_text}",
        }
        if cached and isinstance(cached.get("etag"), str):
            headers["If-None-Match"] = cached["etag"]
        client = self._client or httpx.Client(timeout=NOTICE_TIMEOUT_SECONDS)
        owns_client = self._client is None
        try:
            response = client.get(
                self._endpoint,
                headers=headers,
                params={
                    "version": self._cli_version_text,
                    "channel": self._channel,
                    "os": self._operating_system,
                    "arch": self._architecture,
                },
                timeout=NOTICE_TIMEOUT_SECONDS,
            )
            if response.status_code == 304 and cached is not None:
                refreshed = dict(cached)
                refreshed["fetched_at"] = now.isoformat().replace("+00:00", "Z")
                refreshed["max_age_seconds"] = self._cache_max_age(response)
                return refreshed
            if response.status_code != 200:
                return None
            if len(response.content) > MAX_RESPONSE_BYTES:
                return None
            payload = response.json()
            self._parse_payload(payload)
            return {
                "fetched_at": now.isoformat().replace("+00:00", "Z"),
                "max_age_seconds": self._cache_max_age(response),
                "etag": response.headers.get("ETag"),
                "payload": payload,
            }
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, TypeError):
            return None
        finally:
            if owns_client:
                client.close()

    @staticmethod
    def _cache_max_age(response: httpx.Response) -> int:
        match = re.search(r"(?:^|,)\s*max-age=(\d+)", response.headers.get("Cache-Control", ""))
        if match is None:
            return int(CACHE_TTL.total_seconds())
        return min(int(match.group(1)), int(CACHE_TTL.total_seconds()))

    @staticmethod
    def _parse_payload(payload: object) -> list[Notice]:
        if not isinstance(payload, dict) or set(payload) - {"notices", "generated_at"}:
            raise ValueError("invalid notice response")
        values = payload.get("notices")
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError("invalid notice response")
        notices = [parse_notice(value) for value in values]
        if len({notice.id for notice in notices}) != len(notices):
            raise ValueError("duplicate notice ID")
        return notices

    def _is_applicable(self, notice: Notice, now: datetime) -> bool:
        if notice.start_at is not None and now < notice.start_at:
            return False
        if notice.expires_at is not None and now >= notice.expires_at:
            return False
        if notice.min_cli_version and compare_semver(self._cli_version, notice.min_cli_version) < 0:
            return False
        if notice.max_cli_version and compare_semver(self._cli_version, notice.max_cli_version) > 0:
            return False
        targets = (
            (notice.release_channels, self._channel),
            (notice.operating_systems, self._operating_system),
            (notice.architectures, self._architecture),
        )
        return all(not allowed or actual in allowed for allowed, actual in targets)

    @staticmethod
    def _display_due(notice: Notice, displayed: dict[str, Any], now: datetime) -> bool:
        previous = NoticeManager._safe_timestamp(displayed.get(notice.id))
        if notice.display_policy == "always":
            return True
        if previous is None:
            return True
        if notice.display_policy == "daily":
            return now - previous >= DAILY_INTERVAL
        return False

    @staticmethod
    def _render(notice: Notice) -> str:
        rendered = f"\n[{notice.severity.upper()}] {notice.title}\n{notice.message}\n"
        if notice.url:
            rendered += f"More information: {notice.url}\n"
        return rendered

    def _load_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return {"version": STATE_VERSION, "displayed": {}}
        if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
            return {"version": STATE_VERSION, "displayed": {}}
        return payload

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            if sys.platform != "win32":
                os.chmod(self._state_path.parent, 0o700)
            temporary = self._state_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            if sys.platform != "win32":
                os.chmod(temporary, 0o600)
            os.replace(temporary, self._state_path)
        except OSError:
            return

    @staticmethod
    def _safe_timestamp(value: object) -> datetime | None:
        try:
            return _parse_datetime(value)
        except (ValueError, TypeError):
            return None


def display_notices_safely(
    *,
    base_url: str,
    cli_version: str,
    force_refresh: bool = False,
    ignore_display_policy: bool = False,
    show_empty: bool = False,
) -> None:
    try:
        NoticeManager(base_url=base_url, cli_version=cli_version).display(
            force_refresh=force_refresh,
            ignore_display_policy=ignore_display_policy,
            show_empty=show_empty,
        )
    except Exception:
        # Notice delivery is explicitly best-effort and must never alter command behavior.
        return
