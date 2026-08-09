from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from polygres_cli._vendor.polygres_lib.auth import AUTH_ERROR_CATALOG, AuthErrorCode

SUCCESS = 0
GENERAL_FAILURE = 1
USAGE = 2
AUTH = 3
PERMISSION = 4
NOT_FOUND = 5
CONFLICT = 6
RATE_LIMITED = 7
UNAVAILABLE = 8
LOCAL_DEPENDENCY = 9

HTTP_EXIT_CODES = {
    400: USAGE,
    410: USAGE,
    413: USAGE,
    401: AUTH,
    403: PERMISSION,
    404: NOT_FOUND,
    409: CONFLICT,
    422: USAGE,
    429: RATE_LIMITED,
    500: UNAVAILABLE,
    502: UNAVAILABLE,
    503: UNAVAILABLE,
    504: UNAVAILABLE,
}


@dataclass
class CliError(Exception):
    code: str
    message: str
    exit_code: int = GENERAL_FAILURE
    details: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def __str__(self) -> str:
        return self.message


class UsageError(CliError):
    def __init__(self, message: str, *, code: str = "INVALID_USAGE") -> None:
        super().__init__(code=code, message=message, exit_code=USAGE)


def is_maintenance_error_payload(payload: dict[str, Any] | None) -> bool:
    error = (payload or {}).get("error")
    return (
        isinstance(error, dict)
        and error.get("code") in {"MAINTENANCE_READ_ONLY", "MAINTENANCE_FULL"}
    )


def api_error_from_response(status_code: int, payload: dict[str, Any] | None) -> CliError:
    payload = payload or {}
    error = payload.get("error")
    if not isinstance(error, dict):
        error = {}
    code = str(error.get("code") or _default_code(status_code))
    canonical_code = _LEGACY_AUTH_CODES.get(code, code)
    verification_failure = code in {
        "VECTOR_INDEX_VERIFICATION_FAILED",
        "GRAPH_ACTIVATION_VERIFICATION_FAILED",
    }
    try:
        return auth_failure(
            canonical_code,
            details=error.get("details") if isinstance(error.get("details"), dict) else {},
            request_id=payload.get("request_id"),
        )
    except ValueError:
        return CliError(
            code=code,
            message=str(error.get("message") or _default_message(status_code)),
            details=error.get("details") if isinstance(error.get("details"), dict) else {},
            request_id=payload.get("request_id"),
            exit_code=(
                GENERAL_FAILURE
                if verification_failure
                else HTTP_EXIT_CODES.get(status_code, GENERAL_FAILURE)
            ),
        )


_LEGACY_AUTH_CODES = {
    "AUTH_EXPIRED": "TOKEN_EXPIRED",
    "AUTH_DENIED": "CLI_AUTH_DENIED",
    "AUTH_TIMEOUT": "CLI_AUTH_TIMEOUT",
    "AUTH_RESPONSE_INVALID": "CLI_AUTH_RESPONSE_INVALID",
    "AUTH_REFRESH_INVALID": "INVALID_TOKEN",
}


def auth_failure(
    code: str,
    *,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> CliError:
    canonical_code = _LEGACY_AUTH_CODES.get(code, code)
    try:
        auth_code = AuthErrorCode(canonical_code)
    except ValueError as exc:
        raise ValueError(f"unknown auth error code: {code}") from exc
    descriptor = AUTH_ERROR_CATALOG[auth_code]
    safe_details = {
        key: value
        for key, value in (details or {}).items()
        if key in descriptor.safe_detail_keys
    }
    return CliError(
        code=descriptor.code.value,
        message=descriptor.safe_message,
        exit_code=int(descriptor.cli_exit_code),
        details=safe_details,
        request_id=request_id,
    )


def _default_code(status_code: int) -> str:
    if status_code == 401:
        return "AUTH_REQUIRED"
    if status_code == 403:
        return "PERMISSION_DENIED"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code in {500, 502, 503, 504}:
        return "SERVICE_UNAVAILABLE"
    return "API_ERROR"


def _default_message(status_code: int) -> str:
    if status_code == 401:
        return "Run `polygres login` to continue."
    if status_code == 403:
        return (
            "Permission denied. Confirm the signed-in account has access to the "
            "requested resource, then retry."
        )
    if status_code == 404:
        return (
            "Resource not found. Check the resource identifier and command context "
            "before retrying."
        )
    if status_code == 429:
        return "Request limit reached. Wait for the retry period before trying again."
    if status_code in {500, 502, 503, 504}:
        return (
            "The Polygres API is temporarily unavailable. Wait a minute and retry. "
            "If the failure continues, contact support."
        )
    return "The Polygres API request failed. Please wait a while and retry."
