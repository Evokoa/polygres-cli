from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from uuid import UUID

from ..errors import ERROR_CATALOG, PolygresError, error_record
from .enums import (
    CliExitCode,
    PasswordRequirement,
    ProjectStatus,
    ResetClass,
    RetryClass,
)


class AuthErrorCategory(str, Enum):
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    ACCOUNT_GATE = "account_gate"
    CONFLICT = "conflict"
    RATE_LIMIT = "rate_limit"
    DEPENDENCY = "dependency"
    TERMINAL_SESSION = "terminal_session"
    UNEXPECTED = "unexpected"


class AuthErrorCode(str, Enum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_MODE_NOT_ALLOWED = "AUTH_MODE_NOT_ALLOWED"
    AUTH_NOT_CONFIGURED = "AUTH_NOT_CONFIGURED"
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_EMAIL_REQUIRED = "AUTH_EMAIL_REQUIRED"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    LOCAL_SESSION_CORRUPT = "LOCAL_SESSION_CORRUPT"
    LOCAL_SESSION_RESET_LIMIT_REACHED = "LOCAL_SESSION_RESET_LIMIT_REACHED"
    AUTH_PROVIDER_UNAVAILABLE = "AUTH_PROVIDER_UNAVAILABLE"
    AUTH_PKCE_EXCHANGE_FAILED = "AUTH_PKCE_EXCHANGE_FAILED"
    AUTH_PKCE_VERIFIER_MISSING = "AUTH_PKCE_VERIFIER_MISSING"
    AUTH_ACTION_INVALID = "AUTH_ACTION_INVALID"
    AUTH_ACTION_EXPIRED = "AUTH_ACTION_EXPIRED"
    AUTH_RECOVERY_REQUIRED = "AUTH_RECOVERY_REQUIRED"
    RECOVERY_GRANT_INVALID = "RECOVERY_GRANT_INVALID"
    AUTH_REAUTHENTICATION_REQUIRED = "AUTH_REAUTHENTICATION_REQUIRED"
    AUTH_REAUTHENTICATION_INVALID = "AUTH_REAUTHENTICATION_INVALID"
    AUTH_PASSWORD_MODE_MISMATCH = "AUTH_PASSWORD_MODE_MISMATCH"
    AUTH_WEAK_PASSWORD = "AUTH_WEAK_PASSWORD"
    AUTH_IDENTITY_CHANGED = "AUTH_IDENTITY_CHANGED"
    EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"
    ACCOUNT_NOT_ELIGIBLE = "ACCOUNT_NOT_ELIGIBLE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ADMIN_NOT_ALLOWED = "ADMIN_NOT_ALLOWED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    PROJECT_NOT_READY = "PROJECT_NOT_READY"
    INVITATION_NOT_FOUND = "INVITATION_NOT_FOUND"
    INVITATION_EMAIL_MISMATCH = "INVITATION_EMAIL_MISMATCH"
    INVITATION_EXISTS = "INVITATION_EXISTS"
    INVITATION_EXPIRED = "INVITATION_EXPIRED"
    INVITATION_NOT_PENDING = "INVITATION_NOT_PENDING"
    INVITATION_NOT_RESENDABLE = "INVITATION_NOT_RESENDABLE"
    INVITATION_RESEND_TOO_SOON = "INVITATION_RESEND_TOO_SOON"
    INVITATION_DELIVERY_FAILED = "INVITATION_DELIVERY_FAILED"
    SELF_INVITE_NOT_ALLOWED = "SELF_INVITE_NOT_ALLOWED"
    INVALID_INVITATION_ROLE = "INVALID_INVITATION_ROLE"
    ORG_MEMBERSHIP_LIMIT_EXCEEDED = "ORG_MEMBERSHIP_LIMIT_EXCEEDED"
    LEGAL_ACCEPTANCE_REQUIRED = "LEGAL_ACCEPTANCE_REQUIRED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CLI_AUTH_NOT_CONFIGURED = "CLI_AUTH_NOT_CONFIGURED"
    CLI_AUTH_SESSION_CREATE_FAILED = "CLI_AUTH_SESSION_CREATE_FAILED"
    CLI_AUTH_SESSION_INVALID = "CLI_AUTH_SESSION_INVALID"
    CLI_AUTH_SESSION_NOT_FOUND = "CLI_AUTH_SESSION_NOT_FOUND"
    CLI_AUTH_SESSION_TERMINAL = "CLI_AUTH_SESSION_TERMINAL"
    CLI_AUTH_DENIED = "CLI_AUTH_DENIED"
    CLI_AUTH_EXPIRED = "CLI_AUTH_EXPIRED"
    CLI_AUTH_TIMEOUT = "CLI_AUTH_TIMEOUT"
    CLI_AUTH_RESPONSE_INVALID = "CLI_AUTH_RESPONSE_INVALID"
    API_KEY_INVALID = "API_KEY_INVALID"
    API_KEY_NOT_FOUND = "API_KEY_NOT_FOUND"
    PROJECT_HEADER_REQUIRED = "PROJECT_HEADER_REQUIRED"
    RUNTIME_API_KEY_SNAPSHOT_UNAVAILABLE = "RUNTIME_API_KEY_SNAPSHOT_UNAVAILABLE"
    GATEWAY_RUNTIME_JWT_REQUIRED = "GATEWAY_RUNTIME_JWT_REQUIRED"
    GATEWAY_RUNTIME_JWT_INVALID = "GATEWAY_RUNTIME_JWT_INVALID"
    GATEWAY_RUNTIME_PROJECT_MISMATCH = "GATEWAY_RUNTIME_PROJECT_MISMATCH"
    GATEWAY_RUNTIME_SCOPE_INVALID = "GATEWAY_RUNTIME_SCOPE_INVALID"
    GATEWAY_RUNTIME_SCOPE_DENIED = "GATEWAY_RUNTIME_SCOPE_DENIED"
    GATEWAY_RUNTIME_JWKS_UNAVAILABLE = "GATEWAY_RUNTIME_JWKS_UNAVAILABLE"
    RUNTIME_HOST_INVALID = "RUNTIME_HOST_INVALID"
    RUNTIME_ROUTING_HEADER_REJECTED = "RUNTIME_ROUTING_HEADER_REJECTED"
    RUNTIME_PROJECT_NOT_FOUND = "RUNTIME_PROJECT_NOT_FOUND"
    RUNTIME_PROJECT_NOT_READY = "RUNTIME_PROJECT_NOT_READY"
    EMAIL_DELIVERY_FAILED = "EMAIL_DELIVERY_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    RATE_LIMIT_UNAVAILABLE = "RATE_LIMIT_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class AuthErrorDescriptor:
    code: AuthErrorCode
    category: AuthErrorCategory
    safe_message: str
    message_key: str
    http_status: int | None
    cli_exit_code: CliExitCode
    retry_class: RetryClass
    reset_class: ResetClass
    safe_detail_keys: frozenset[str]


AUTH_ERROR_CATALOG: Mapping[AuthErrorCode, AuthErrorDescriptor] = MappingProxyType(
    {
        code: AuthErrorDescriptor(
            code=code,
            category=AuthErrorCategory(ERROR_CATALOG[code.value].category),
            safe_message=ERROR_CATALOG[code.value].message,
            message_key=ERROR_CATALOG[code.value].message_key,
            http_status=ERROR_CATALOG[code.value].http_status,
            cli_exit_code=CliExitCode(ERROR_CATALOG[code.value].cli_exit_code),
            retry_class=RetryClass(ERROR_CATALOG[code.value].retry_class),
            reset_class=ResetClass(ERROR_CATALOG[code.value].reset_class),
            safe_detail_keys=ERROR_CATALOG[code.value].safe_detail_fields,
        )
        for code in AuthErrorCode
    }
)

if set(AUTH_ERROR_CATALOG) != set(AuthErrorCode):
    raise RuntimeError("global error catalog must define every AuthErrorCode exactly once")


_FIELD_PATH = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")


def _validate_safe_details(code: AuthErrorCode, details: Mapping[str, object]) -> None:
    if code is AuthErrorCode.VALIDATION_ERROR and details:
        field = details.get("field")
        if not isinstance(field, str) or _FIELD_PATH.fullmatch(field) is None:
            raise ValueError("field must be a schema-owned field path")
    elif code is AuthErrorCode.AUTH_WEAK_PASSWORD and details:
        raw_requirements = details.get("requirements")
        if not isinstance(raw_requirements, (list, tuple)):
            raise ValueError("requirements must be present")
        try:
            requirements = tuple(PasswordRequirement(item) for item in raw_requirements)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown password requirement") from exc
        canonical = tuple(item for item in PasswordRequirement if item in requirements)
        if requirements != canonical:
            raise ValueError("password requirements must be unique and canonical")
        minimum = details.get("minimum_length")
        if minimum is not None and (
            PasswordRequirement.LENGTH not in requirements
            or isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or not 1 <= minimum <= 1024
        ):
            raise ValueError("minimum_length requires a known length requirement")
    elif (
        code in {AuthErrorCode.PROJECT_NOT_READY, AuthErrorCode.RUNTIME_PROJECT_NOT_READY}
        and details
    ):
        try:
            ProjectStatus(details.get("status"))
        except (TypeError, ValueError) as exc:
            raise ValueError("status must be a ProjectStatus") from exc
    elif code is AuthErrorCode.INVITATION_RESEND_TOO_SOON and details:
        timestamp = details.get("resend_available_at")
        seconds = details.get("remaining_seconds")
        if not isinstance(timestamp, str):
            raise ValueError("resend_available_at must be an RFC 3339 timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("resend_available_at must be an RFC 3339 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("resend_available_at must include a UTC offset")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
            raise ValueError("remaining_seconds must be a non-negative integer")
    elif code is AuthErrorCode.ORG_MEMBERSHIP_LIMIT_EXCEEDED and details:
        try:
            for key in ("current_organization_id", "invited_organization_id"):
                raw = details[key]
                if not isinstance(raw, str) or str(UUID(raw)) != raw:
                    raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("organization details must contain canonical UUIDs") from exc
    elif code is AuthErrorCode.AUTH_IDENTITY_CHANGED and details:
        for key in ("previous_epoch", "current_epoch"):
            value = details.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("identity epochs must be non-negative integers")


class AuthError(PolygresError):
    def __init__(
        self,
        code: AuthErrorCode,
        *,
        details: Mapping[str, object] | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        descriptor = AUTH_ERROR_CATALOG[code]
        supplied = dict(details or {})
        unknown = supplied.keys() - descriptor.safe_detail_keys
        if unknown:
            raise ValueError(f"unsafe error detail keys: {sorted(unknown)!r}")
        _validate_safe_details(code, supplied)
        if retry_after_seconds is not None and (
            isinstance(retry_after_seconds, bool)
            or not isinstance(retry_after_seconds, int)
            or not 0 <= retry_after_seconds <= 86_400
            or descriptor.retry_class is RetryClass.NEVER
        ):
            raise ValueError("invalid retry_after_seconds for auth error")
        super().__init__(error_record(code.value, details=supplied))
        self.code = code
        self.retry_class = descriptor.retry_class
        self.reset_class = descriptor.reset_class
        self.message_key = descriptor.message_key
        self.retry_after_seconds = retry_after_seconds

    def __repr__(self) -> str:
        return f"AuthError(code={self.code.value!r})"
