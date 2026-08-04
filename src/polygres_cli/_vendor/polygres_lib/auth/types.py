from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from ..core.types import SecretValue
from .enums import JwtAlgorithm, LegalAcceptanceMethod
from .principals import AuthPrincipal


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: str
    now: datetime
    trace_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not 1 <= len(self.request_id) <= 128:
            raise ValueError("request_id must contain 1..128 characters")
        if not self.request_id.isascii() or not self.request_id.isprintable():
            raise ValueError("request_id must be printable ASCII")
        if not _aware(self.now):
            raise ValueError("now must be timezone-aware")


@dataclass(frozen=True, slots=True, repr=False)
class AuthTransport:
    authorization: str | None = field(repr=False)
    project_header: str | None = None
    path_project_id: str | None = None
    path_organization_id: UUID | None = None
    peer_ip: str | None = None
    forwarded: str | None = field(default=None, repr=False)
    x_forwarded_for: str | None = field(default=None, repr=False)


@dataclass(slots=True)
class RequestAuthMemo:
    principal: AuthPrincipal | None = None
    decisions: dict[tuple[str, str | None], object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupabasePublicAuthConfig:
    base_url: str
    api_key: SecretValue
    jwt_audience: str
    allowed_algorithms: tuple[JwtAlgorithm, ...] = (
        JwtAlgorithm.RS256,
        JwtAlgorithm.ES256,
    )
    legacy_hs256_secret: SecretValue | None = None
    read_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        normalized = self.base_url.rstrip("/")
        if normalized.endswith("/auth/v1"):
            normalized = normalized.removesuffix("/auth/v1")
        if normalized.endswith("/auth/v1"):
            raise ValueError(
                "Authentication service base URL contains a duplicated authentication path"
            )
        if not normalized.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError(
                "Authentication service base URL must use HTTPS or configured loopback HTTP"
            )
        if not self.jwt_audience or self.read_timeout_seconds <= 0:
            raise ValueError("Invalid public authentication configuration")
        if JwtAlgorithm.HS256 in self.allowed_algorithms and self.legacy_hs256_secret is None:
            raise ValueError("HS256 requires an explicit legacy secret")
        object.__setattr__(self, "base_url", normalized)

    @property
    def auth_base_url(self) -> str:
        return f"{self.base_url}/auth/v1"


@dataclass(frozen=True, slots=True)
class SupabaseAdminAuthConfig:
    service_role_key: SecretValue
    request_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.request_timeout_seconds <= 0:
            raise ValueError("request timeout must be positive")


@dataclass(frozen=True, slots=True)
class JwksCacheConfig:
    ttl_seconds: int = 600
    unknown_key_refreshes: Literal[1] = 1

    def __post_init__(self) -> None:
        if not 1 <= self.ttl_seconds <= 3600:
            raise ValueError("JWKS TTL must be between 1 and 3600 seconds")


@dataclass(frozen=True, slots=True)
class LegalVersionSet:
    terms_version: str = "terms_2026_06_27"
    privacy_version: str = "privacy_2026_06_27"
    method: LegalAcceptanceMethod = LegalAcceptanceMethod.EXPLICIT_ACCEPT_BUTTON


@dataclass(frozen=True, slots=True)
class AuthIntentSigningConfig:
    issuer: str
    audience: str
    key_id: str
    signing_key: SecretValue
    verification_keys: Mapping[str, SecretValue]
    lifetime_seconds: int = 86_400

    def __post_init__(self) -> None:
        audience = urlsplit(self.audience)
        loopback = audience.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            self.issuer != "polygres-auth"
            or not 1 <= len(self.key_id) <= 64
            or self.key_id not in self.verification_keys
            or not audience.netloc
            or audience.path not in {"", "/"}
            or audience.query
            or audience.fragment
            or (audience.scheme != "https" and not (audience.scheme == "http" and loopback))
        ):
            raise ValueError("invalid Auth intent signing configuration")
        if not 1 <= self.lifetime_seconds <= 86_400:
            raise ValueError("Auth intent lifetime must be 1..86400 seconds")
        object.__setattr__(
            self, "verification_keys", MappingProxyType(dict(self.verification_keys))
        )


@dataclass(frozen=True, slots=True)
class InvitationDeliveryConfig:
    dashboard_origin: str
    confirm_path: str = "/auth/confirm"
    organization_template: Literal["organization_invitation"] = "organization_invitation"
    admin_template: Literal["admin_user_invitation"] = "admin_user_invitation"
    custom_admin_template: Literal["custom_admin_user_invitation"] = "custom_admin_user_invitation"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.dashboard_origin)
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback))
            or not self.confirm_path.startswith("/")
            or self.confirm_path.startswith("//")
            or "?" in self.confirm_path
            or "#" in self.confirm_path
        ):
            raise ValueError("invalid invitation delivery configuration")
        object.__setattr__(self, "dashboard_origin", self.dashboard_origin.rstrip("/"))


@dataclass(frozen=True, slots=True)
class CliAuthConfig:
    dashboard_base_url: str
    pending_ttl_seconds: int = 600
    access_ttl_seconds: int = 3_600
    refresh_ttl_seconds: int = 2_592_000
    poll_interval_seconds: int = 2

    def __post_init__(self) -> None:
        if min(
            self.pending_ttl_seconds,
            self.access_ttl_seconds,
            self.refresh_ttl_seconds,
            self.poll_interval_seconds,
        ) < 1:
            raise ValueError("CLI authentication TTLs and poll interval must be positive")
        if self.poll_interval_seconds > self.pending_ttl_seconds:
            raise ValueError("CLI poll interval cannot exceed pending-session TTL")


@dataclass(frozen=True, slots=True)
class CliBrowserStateSigningConfig:
    issuer: Literal["polygres-cli-auth"]
    audience: str
    key_id: str
    signing_key: SecretValue
    verification_keys: Mapping[str, SecretValue]

    def __post_init__(self) -> None:
        if (
            self.issuer != "polygres-cli-auth"
            or not self.audience
            or not 1 <= len(self.key_id) <= 64
            or self.key_id not in self.verification_keys
        ):
            raise ValueError("invalid CLI browser-state signing configuration")
        object.__setattr__(
            self, "verification_keys", MappingProxyType(dict(self.verification_keys))
        )


@dataclass(frozen=True, slots=True)
class TrustedProxyConfig:
    trusted_proxy_cidrs: tuple[str, ...] = ()
    forwarded_header_precedence: tuple[Literal["forwarded", "x_forwarded_for"], ...] = (
        "forwarded",
        "x_forwarded_for",
    )

    def __post_init__(self) -> None:
        for cidr in self.trusted_proxy_cidrs:
            ipaddress.ip_network(cidr, strict=False)
        if len(set(self.forwarded_header_precedence)) != len(self.forwarded_header_precedence):
            raise ValueError("forwarded-header precedence contains duplicates")


@dataclass(frozen=True, slots=True)
class GatewayRuntimeJwtConfig:
    issuer: str
    audience: str
    key_id: str
    private_key_pem: SecretValue | None
    public_jwks_file: Path | None
    ttl_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.issuer or not self.audience or not 1 <= len(self.key_id) <= 64:
            raise ValueError("invalid gateway runtime JWT identity configuration")
        if not 1 <= self.ttl_seconds <= 60:
            raise ValueError("gateway runtime JWT TTL must be 1..60 seconds")
        if self.private_key_pem is None and self.public_jwks_file is None:
            raise ValueError("a signing key or public JWKS file is required")


@dataclass(frozen=True, slots=True)
class DelegatedRuntimeJwtConfig:
    issuer: str
    audience: str
    key_id: str
    private_key_pem: SecretValue | None
    public_jwks_file: Path | None
    read_ttl_seconds: int = 300
    manage_ttl_seconds: int = 60
    clock_skew_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.issuer or not self.audience or not 1 <= len(self.key_id) <= 64:
            raise ValueError("invalid delegated Runtime JWT identity configuration")
        if not 1 <= self.read_ttl_seconds <= 300:
            raise ValueError("delegated Runtime read TTL must be 1..300 seconds")
        if not 1 <= self.manage_ttl_seconds <= 60:
            raise ValueError("delegated Runtime manage TTL must be 1..60 seconds")
        if not 0 <= self.clock_skew_seconds <= 60:
            raise ValueError("delegated Runtime clock skew must be 0..60 seconds")
        if self.private_key_pem is None and self.public_jwks_file is None:
            raise ValueError("a signing key or public JWKS file is required")
