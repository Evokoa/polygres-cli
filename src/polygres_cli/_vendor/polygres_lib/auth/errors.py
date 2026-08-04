from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from uuid import UUID

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


def _descriptor(
    code: AuthErrorCode,
    category: AuthErrorCategory,
    message: str,
    status: int | None,
    cli: CliExitCode,
    retry: RetryClass = RetryClass.NEVER,
    reset: ResetClass = ResetClass.NONE,
    details: frozenset[str] = frozenset(),
) -> AuthErrorDescriptor:
    return AuthErrorDescriptor(
        code=code,
        category=category,
        safe_message=message,
        message_key=f"polygres.auth.{code.value.lower()}",
        http_status=status,
        cli_exit_code=cli,
        retry_class=retry,
        reset_class=reset,
        safe_detail_keys=details,
    )


_C = AuthErrorCategory
_E = CliExitCode
_R = RetryClass
_S = ResetClass

# code, category, HTTP status, CLI exit, retry, reset, safe message
_CATALOG_ROWS = (
    (
        "AUTH_REQUIRED",
        _C.AUTHENTICATION,
        401,
        _E.AUTH,
        _R.USER_RETRY,
        _S.NONE,
        "Authentication is required.",
    ),
    (
        "AUTH_MODE_NOT_ALLOWED",
        _C.AUTHORIZATION,
        403,
        _E.PERMISSION,
        _R.NEVER,
        _S.NONE,
        "This credential cannot be used for this operation.",
    ),
    (
        "AUTH_NOT_CONFIGURED",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.NEVER,
        _S.NONE,
        "Authentication is not configured for this service.",
    ),
    (
        "AUTH_INVALID_CREDENTIALS",
        _C.AUTHENTICATION,
        401,
        _E.AUTH,
        _R.USER_RETRY,
        _S.NONE,
        "The email or password is incorrect.",
    ),
    (
        "AUTH_EMAIL_REQUIRED",
        _C.TERMINAL_SESSION,
        401,
        _E.AUTH,
        _R.NEVER,
        _S.LOCAL_SESSION,
        "Your identity provider did not return an email address. "
        "Use another sign-in method or allow email access.",
    ),
    (
        "INVALID_TOKEN",
        _C.AUTHENTICATION,
        401,
        _E.AUTH,
        _R.USER_RETRY,
        _S.NONE,
        "The authentication token is invalid.",
    ),
    (
        "TOKEN_EXPIRED",
        _C.AUTHENTICATION,
        401,
        _E.AUTH,
        _R.BOUNDED_RETRY,
        _S.NONE,
        "The authentication token has expired.",
    ),
    (
        "LOCAL_SESSION_CORRUPT",
        _C.TERMINAL_SESSION,
        401,
        _E.AUTH,
        _R.NEVER,
        _S.LOCAL_SESSION,
        "The local session cannot be read and must be repaired.",
    ),
    (
        "LOCAL_SESSION_RESET_LIMIT_REACHED",
        _C.TERMINAL_SESSION,
        409,
        _E.CONFLICT,
        _R.USER_RETRY,
        _S.NONE,
        "Automatic session repair has already been attempted.",
    ),
    (
        "AUTH_PROVIDER_UNAVAILABLE",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.DEPENDENCY_RETRY,
        _S.NONE,
        "Authentication is temporarily unavailable. Wait a moment and try again.",
    ),
    (
        "AUTH_PKCE_EXCHANGE_FAILED",
        _C.AUTHENTICATION,
        400,
        _E.AUTH,
        _R.USER_RETRY,
        _S.NONE,
        "The sign-in callback could not be verified. Restart sign-in in the same browser.",
    ),
    (
        "AUTH_PKCE_VERIFIER_MISSING",
        _C.AUTHENTICATION,
        400,
        _E.AUTH,
        _R.USER_RETRY,
        _S.NONE,
        "This sign-in link must be restarted in the browser that began it.",
    ),
    (
        "AUTH_ACTION_INVALID",
        _C.AUTHENTICATION,
        400,
        _E.AUTH,
        _R.USER_RETRY,
        _S.NONE,
        "This authentication action is invalid.",
    ),
    (
        "AUTH_ACTION_EXPIRED",
        _C.AUTHENTICATION,
        410,
        _E.CONFLICT,
        _R.USER_RETRY,
        _S.NONE,
        "This authentication action has expired.",
    ),
    (
        "AUTH_RECOVERY_REQUIRED",
        _C.ACCOUNT_GATE,
        403,
        _E.PERMISSION,
        _R.USER_RETRY,
        _S.NONE,
        "A verified password-recovery session is required.",
    ),
    (
        "RECOVERY_GRANT_INVALID",
        _C.ACCOUNT_GATE,
        403,
        _E.PERMISSION,
        _R.USER_RETRY,
        _S.NONE,
        "The password-recovery session is no longer valid.",
    ),
    (
        "AUTH_REAUTHENTICATION_REQUIRED",
        _C.ACCOUNT_GATE,
        403,
        _E.PERMISSION,
        _R.USER_RETRY,
        _S.NONE,
        "Reauthenticate to continue.",
    ),
    (
        "AUTH_REAUTHENTICATION_INVALID",
        _C.AUTHENTICATION,
        403,
        _E.PERMISSION,
        _R.USER_RETRY,
        _S.NONE,
        "The reauthentication proof is invalid or expired.",
    ),
    (
        "AUTH_PASSWORD_MODE_MISMATCH",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.NEVER,
        _S.NONE,
        "Password-change security is not configured consistently.",
    ),
    (
        "AUTH_WEAK_PASSWORD",
        _C.VALIDATION,
        422,
        _E.USAGE,
        _R.USER_RETRY,
        _S.NONE,
        "The password does not meet the configured security requirements.",
    ),
    (
        "AUTH_IDENTITY_CHANGED",
        _C.CONFLICT,
        None,
        _E.CONFLICT,
        _R.BOUNDED_RETRY,
        _S.NONE,
        "The signed-in identity changed before the operation completed.",
    ),
    (
        "EMAIL_NOT_VERIFIED",
        _C.ACCOUNT_GATE,
        403,
        _E.PERMISSION,
        _R.USER_RETRY,
        _S.NONE,
        "Verify the account email before continuing.",
    ),
    (
        "ACCOUNT_NOT_ELIGIBLE",
        _C.ACCOUNT_GATE,
        403,
        _E.PERMISSION,
        _R.NEVER,
        _S.NONE,
        "This account cannot perform the requested action.",
    ),
    (
        "APPROVAL_REQUIRED",
        _C.ACCOUNT_GATE,
        403,
        _E.PERMISSION,
        _R.USER_RETRY,
        _S.NONE,
        "Account approval is required.",
    ),
    (
        "ADMIN_NOT_ALLOWED",
        _C.AUTHORIZATION,
        403,
        _E.PERMISSION,
        _R.NEVER,
        _S.NONE,
        "Administrator access is required.",
    ),
    (
        "PERMISSION_DENIED",
        _C.AUTHORIZATION,
        403,
        _E.PERMISSION,
        _R.NEVER,
        _S.NONE,
        "Permission denied.",
    ),
    ("NOT_FOUND", _C.AUTHORIZATION, 404, _E.NOT_FOUND, _R.NEVER, _S.NONE, "Resource not found."),
    (
        "PROJECT_NOT_READY",
        _C.CONFLICT,
        409,
        _E.CONFLICT,
        _R.USER_RETRY,
        _S.NONE,
        "The project is not ready for this operation.",
    ),
    (
        "INVITATION_NOT_FOUND",
        _C.AUTHORIZATION,
        404,
        _E.NOT_FOUND,
        _R.NEVER,
        _S.NONE,
        "Invitation not found.",
    ),
    (
        "INVITATION_EMAIL_MISMATCH",
        _C.ACCOUNT_GATE,
        403,
        _E.PERMISSION,
        _R.USER_RETRY,
        _S.NONE,
        "Sign in with the email address that received this invitation.",
    ),
    (
        "INVITATION_EXISTS",
        _C.CONFLICT,
        409,
        _E.CONFLICT,
        _R.USER_RETRY,
        _S.NONE,
        "A pending invitation already exists.",
    ),
    (
        "INVITATION_EXPIRED",
        _C.CONFLICT,
        410,
        _E.CONFLICT,
        _R.USER_RETRY,
        _S.NONE,
        "This invitation has expired.",
    ),
    (
        "INVITATION_NOT_PENDING",
        _C.CONFLICT,
        409,
        _E.CONFLICT,
        _R.NEVER,
        _S.NONE,
        "This invitation is no longer pending.",
    ),
    (
        "INVITATION_NOT_RESENDABLE",
        _C.CONFLICT,
        409,
        _E.CONFLICT,
        _R.NEVER,
        _S.NONE,
        "This invitation cannot be resent.",
    ),
    (
        "INVITATION_RESEND_TOO_SOON",
        _C.RATE_LIMIT,
        429,
        _E.RATE_LIMITED,
        _R.BOUNDED_RETRY,
        _S.NONE,
        "This invitation was sent recently. Try again later.",
    ),
    (
        "INVITATION_DELIVERY_FAILED",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.DEPENDENCY_RETRY,
        _S.NONE,
        "The invitation email couldn’t be delivered. Check the recipient address, then "
        "resend the invitation or create a new one.",
    ),
    (
        "SELF_INVITE_NOT_ALLOWED",
        _C.VALIDATION,
        400,
        _E.USAGE,
        _R.USER_RETRY,
        _S.NONE,
        "You cannot invite your own email address.",
    ),
    (
        "INVALID_INVITATION_ROLE",
        _C.VALIDATION,
        422,
        _E.USAGE,
        _R.USER_RETRY,
        _S.NONE,
        "The invitation role is invalid.",
    ),
    (
        "ORG_MEMBERSHIP_LIMIT_EXCEEDED",
        _C.CONFLICT,
        409,
        _E.CONFLICT,
        _R.USER_RETRY,
        _S.NONE,
        "This account already belongs to an active organization.",
    ),
    (
        "LEGAL_ACCEPTANCE_REQUIRED",
        _C.VALIDATION,
        422,
        _E.USAGE,
        _R.USER_RETRY,
        _S.NONE,
        "Current legal terms must be accepted to continue.",
    ),
    (
        "VALIDATION_ERROR",
        _C.VALIDATION,
        422,
        _E.USAGE,
        _R.USER_RETRY,
        _S.NONE,
        "The request is invalid. Review the request fields and try again.",
    ),
    (
        "CLI_AUTH_NOT_CONFIGURED",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.NEVER,
        _S.NONE,
        "CLI authentication is not configured.",
    ),
    (
        "CLI_AUTH_SESSION_CREATE_FAILED",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.DEPENDENCY_RETRY,
        _S.NONE,
        "The CLI login session could not be created.",
    ),
    (
        "CLI_AUTH_SESSION_INVALID",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.DEPENDENCY_RETRY,
        _S.NONE,
        "CLI authentication state is unavailable.",
    ),
    (
        "CLI_AUTH_SESSION_NOT_FOUND",
        _C.AUTHENTICATION,
        404,
        _E.NOT_FOUND,
        _R.NEVER,
        _S.NONE,
        "CLI login session not found.",
    ),
    (
        "CLI_AUTH_SESSION_TERMINAL",
        _C.CONFLICT,
        409,
        _E.CONFLICT,
        _R.NEVER,
        _S.NONE,
        "The CLI login session is no longer pending.",
    ),
    (
        "CLI_AUTH_DENIED",
        _C.AUTHENTICATION,
        None,
        _E.AUTH,
        _R.USER_RETRY,
        _S.NONE,
        "CLI authentication was denied.",
    ),
    (
        "CLI_AUTH_EXPIRED",
        _C.AUTHENTICATION,
        None,
        _E.AUTH,
        _R.USER_RETRY,
        _S.NONE,
        "The CLI authentication request expired.",
    ),
    (
        "CLI_AUTH_TIMEOUT",
        _C.DEPENDENCY,
        None,
        _E.UNAVAILABLE,
        _R.DEPENDENCY_RETRY,
        _S.NONE,
        "CLI authentication timed out.",
    ),
    (
        "CLI_AUTH_RESPONSE_INVALID",
        _C.DEPENDENCY,
        None,
        _E.UNAVAILABLE,
        _R.DEPENDENCY_RETRY,
        _S.NONE,
        "The CLI received an invalid authentication response.",
    ),
    (
        "API_KEY_INVALID",
        _C.AUTHENTICATION,
        401,
        _E.AUTH,
        _R.NEVER,
        _S.NONE,
        "The API key is invalid.",
    ),
    (
        "API_KEY_NOT_FOUND",
        _C.AUTHORIZATION,
        404,
        _E.NOT_FOUND,
        _R.NEVER,
        _S.NONE,
        "API key not found.",
    ),
    (
        "PROJECT_HEADER_REQUIRED",
        _C.VALIDATION,
        400,
        _E.USAGE,
        _R.USER_RETRY,
        _S.NONE,
        "X-Polygres-Project is required and must match the route project.",
    ),
    (
        "RUNTIME_API_KEY_SNAPSHOT_UNAVAILABLE",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.DEPENDENCY_RETRY,
        _S.NONE,
        "Runtime API-key state is temporarily unavailable.",
    ),
    (
        "GATEWAY_RUNTIME_JWT_REQUIRED",
        _C.AUTHENTICATION,
        401,
        _E.AUTH,
        _R.NEVER,
        _S.NONE,
        "A Gateway Runtime token is required.",
    ),
    (
        "GATEWAY_RUNTIME_JWT_INVALID",
        _C.AUTHENTICATION,
        401,
        _E.AUTH,
        _R.NEVER,
        _S.NONE,
        "The Gateway Runtime token is invalid.",
    ),
    (
        "GATEWAY_RUNTIME_PROJECT_MISMATCH",
        _C.AUTHORIZATION,
        403,
        _E.PERMISSION,
        _R.NEVER,
        _S.NONE,
        "The Gateway Runtime token is for a different project.",
    ),
    (
        "GATEWAY_RUNTIME_SCOPE_INVALID",
        _C.AUTHORIZATION,
        403,
        _E.PERMISSION,
        _R.NEVER,
        _S.NONE,
        "The Gateway Runtime token scope is invalid.",
    ),
    (
        "GATEWAY_RUNTIME_SCOPE_DENIED",
        _C.AUTHORIZATION,
        403,
        _E.PERMISSION,
        _R.NEVER,
        _S.NONE,
        "The Gateway Runtime token does not allow this operation.",
    ),
    (
        "GATEWAY_RUNTIME_JWKS_UNAVAILABLE",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.DEPENDENCY_RETRY,
        _S.NONE,
        "Gateway Runtime signing keys are unavailable.",
    ),
    (
        "RUNTIME_HOST_INVALID",
        _C.VALIDATION,
        400,
        _E.USAGE,
        _R.USER_RETRY,
        _S.NONE,
        "The runtime host is invalid.",
    ),
    (
        "RUNTIME_ROUTING_HEADER_REJECTED",
        _C.VALIDATION,
        400,
        _E.USAGE,
        _R.NEVER,
        _S.NONE,
        "A client-supplied runtime routing header is not allowed.",
    ),
    (
        "RUNTIME_PROJECT_NOT_FOUND",
        _C.AUTHORIZATION,
        404,
        _E.NOT_FOUND,
        _R.NEVER,
        _S.NONE,
        "Runtime project not found.",
    ),
    (
        "RUNTIME_PROJECT_NOT_READY",
        _C.CONFLICT,
        409,
        _E.CONFLICT,
        _R.USER_RETRY,
        _S.NONE,
        "The runtime project is not ready.",
    ),
    (
        "EMAIL_DELIVERY_FAILED",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.DEPENDENCY_RETRY,
        _S.NONE,
        "The email couldn’t be delivered. Wait a moment and try the email action again.",
    ),
    (
        "RATE_LIMITED",
        _C.RATE_LIMIT,
        429,
        _E.RATE_LIMITED,
        _R.BOUNDED_RETRY,
        _S.NONE,
        "Too many requests. Try again later.",
    ),
    (
        "RATE_LIMIT_UNAVAILABLE",
        _C.DEPENDENCY,
        503,
        _E.UNAVAILABLE,
        _R.DEPENDENCY_RETRY,
        _S.NONE,
        "Request-rate protection is temporarily unavailable.",
    ),
    (
        "INTERNAL_ERROR",
        _C.UNEXPECTED,
        500,
        _E.UNAVAILABLE,
        _R.NEVER,
        _S.NONE,
        "The authentication request failed. Please wait a while and try again. If it "
        "continues, contact support.",
    ),
)

_SAFE_DETAIL_KEYS = {
    AuthErrorCode.VALIDATION_ERROR: frozenset({"field"}),
    AuthErrorCode.INVITATION_DELIVERY_FAILED: frozenset({"stage"}),
    AuthErrorCode.AUTH_WEAK_PASSWORD: frozenset({"minimum_length", "requirements"}),
    AuthErrorCode.PROJECT_NOT_READY: frozenset({"status"}),
    AuthErrorCode.RUNTIME_PROJECT_NOT_READY: frozenset({"status"}),
    AuthErrorCode.INVITATION_RESEND_TOO_SOON: frozenset(
        {"resend_available_at", "remaining_seconds"}
    ),
    AuthErrorCode.ORG_MEMBERSHIP_LIMIT_EXCEEDED: frozenset(
        {"current_organization_id", "invited_organization_id"}
    ),
    AuthErrorCode.AUTH_IDENTITY_CHANGED: frozenset({"previous_epoch", "current_epoch"}),
}

AUTH_ERROR_CATALOG: Mapping[AuthErrorCode, AuthErrorDescriptor] = MappingProxyType(
    {
        (code := AuthErrorCode(code_name)): _descriptor(
            code,
            category,
            message,
            status,
            cli,
            retry,
            reset,
            _SAFE_DETAIL_KEYS.get(code, frozenset()),
        )
        for code_name, category, status, cli, retry, reset, message in _CATALOG_ROWS
    }
)

if set(AUTH_ERROR_CATALOG) != set(AuthErrorCode):
    raise RuntimeError("auth error catalog must define every AuthErrorCode exactly once")


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


class PolygresError(Exception):
    code: str | Enum
    message: str
    status_code: int | None
    details: Mapping[str, object]
    retry_class: RetryClass
    reset_class: ResetClass
    message_key: str


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
        super().__init__(descriptor.safe_message)
        self.code = code
        self.message = descriptor.safe_message
        self.status_code = descriptor.http_status
        self.details = supplied
        self.retry_class = descriptor.retry_class
        self.reset_class = descriptor.reset_class
        self.message_key = descriptor.message_key
        self.retry_after_seconds = retry_after_seconds

    def __repr__(self) -> str:
        return f"AuthError(code={self.code.value!r})"
