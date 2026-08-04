from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from polygres_cli._vendor.polygres_lib.auth import (
    CliClientInfo,
    CliLoginPollApproved,
    CliLoginPollRequest,
    CliLoginPollResponse,
    CliLoginStartRequest,
    CliLoginStartResponse,
    CliSessionRefreshRequest,
    CliSessionRefreshResponse,
    CliSessionRevokeRequest,
    SecretCredential,
)
from polygres_cli.cli_errors import auth_failure


def clear_auth(config: dict[str, Any]) -> dict[str, Any]:
    config.pop("auth", None)
    return config


def start_request(*, version: str) -> dict[str, Any]:
    command = CliLoginStartRequest(client=CliClientInfo(version=version))
    return command.model_dump(mode="json")


def poll_request(*, login_session_id: str, poll_token: str) -> dict[str, Any]:
    command = CliLoginPollRequest(
        login_session_id=login_session_id,
        poll_token=SecretCredential(poll_token),
        device_code=None,
    )
    return {
        "login_session_id": command.login_session_id,
        "poll_token": command.poll_token.reveal() if command.poll_token is not None else None,
    }


def refresh_request(*, refresh_token: str) -> dict[str, Any]:
    command = CliSessionRefreshRequest(refresh_token=SecretCredential(refresh_token))
    return {"refresh_token": command.refresh_token.reveal()}


def revoke_request(*, refresh_token: str) -> dict[str, Any]:
    command = CliSessionRevokeRequest(refresh_token=SecretCredential(refresh_token))
    return {"refresh_token": command.refresh_token.reveal()}


def validate_start_response(payload: dict[str, Any]) -> tuple[str, str, str, datetime, int]:
    response = _decode_start_response(payload)
    return (
        response.login_session_id,
        response.browser_url,
        response.poll_token.reveal(),
        response.expires_at.astimezone(timezone.utc),
        min(response.poll_interval_seconds, 30),
    )


def normalize_poll_response(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = CliLoginPollResponse.model_validate(payload)
    except ValidationError:
        return _decode_legacy_poll_response(payload)

    result = response.result
    normalized: dict[str, Any] = {
        "request_id": response.request_id,
        "status": result.state.value,
    }
    if isinstance(result, CliLoginPollApproved):
        normalized.update(_stored_auth_from_pair(result.token_pair))
    elif hasattr(result, "poll_interval_seconds"):
        normalized["poll_interval_seconds"] = result.poll_interval_seconds
    return normalized


def normalize_refresh_response(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = CliSessionRefreshResponse.model_validate(payload)
    except ValidationError:
        return _decode_legacy_refresh_response(payload)
    return {
        "request_id": response.request_id,
        **_stored_auth_from_pair(response.token_pair),
    }


def validated_approved_auth(payload: dict[str, Any]) -> dict[str, Any]:
    required = {
        "access_token",
        "refresh_token",
        "access_expires_at",
        "refresh_expires_at",
        "user",
    }
    if not required.issubset(payload):
        raise auth_failure("CLI_AUTH_RESPONSE_INVALID")
    return {key: payload[key] for key in required}


def _decode_start_response(payload: dict[str, Any]) -> CliLoginStartResponse:
    try:
        return CliLoginStartResponse.model_validate(payload)
    except ValidationError:
        return _decode_legacy_start_response(payload)


def _decode_legacy_start_response(payload: dict[str, Any]) -> CliLoginStartResponse:
    """Read the pre-0.1 contract while deployed clients and servers roll forward."""
    compatibility_payload = dict(payload)
    compatibility_payload.setdefault("request_id", "legacy_cli_auth_start")
    compatibility_payload.setdefault("device_code", "0000-0000")
    try:
        return CliLoginStartResponse.model_validate(compatibility_payload)
    except ValidationError as exc:
        raise auth_failure("CLI_AUTH_RESPONSE_INVALID") from exc


def _decode_legacy_poll_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Read the pre-0.1 flattened poll union without weakening canonical DTO parsing."""
    status = payload.get("status")
    if status == "pending":
        interval = payload.get("poll_interval_seconds", 2)
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
            raise auth_failure("CLI_AUTH_RESPONSE_INVALID")
        return {**payload, "poll_interval_seconds": min(interval, 30)}
    if status in {"denied", "expired", "consumed"}:
        return payload
    if status != "approved":
        raise auth_failure("CLI_AUTH_RESPONSE_INVALID", details={"status": status})

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    user = payload.get("user")
    expires_at = payload.get("expires_at")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise auth_failure("CLI_AUTH_RESPONSE_INVALID")
    if not isinstance(user, dict) or not isinstance(expires_at, str):
        raise auth_failure("CLI_AUTH_RESPONSE_INVALID")
    _parse_timestamp(expires_at)
    return {
        **payload,
        "access_expires_at": expires_at,
        "refresh_expires_at": expires_at,
    }


def _decode_legacy_refresh_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Read the pre-0.1 flattened refresh result and normalize its expiry alias."""
    normalized = _decode_legacy_poll_response({"status": "approved", **payload})
    normalized.pop("status", None)
    return normalized


def _stored_auth_from_pair(pair: Any) -> dict[str, Any]:
    return {
        "access_token": pair.access_token.reveal(),
        "refresh_token": pair.refresh_token.reveal(),
        "access_expires_at": pair.access_expires_at.isoformat(),
        "refresh_expires_at": pair.refresh_expires_at.isoformat(),
        "user": {
            "subject_id": str(pair.user.subject_id),
            "email": pair.user.email,
        },
    }


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise auth_failure("CLI_AUTH_RESPONSE_INVALID") from exc
    if parsed.tzinfo is None:
        raise auth_failure("CLI_AUTH_RESPONSE_INVALID")
    return parsed
