from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from .enums import (
    ApiKeyStatus,
    AssuranceLevel,
    AuthenticationMethod,
    CredentialKind,
    EmailVerificationSource,
    OAuthProvider,
    OrganizationRole,
    Permission,
    PrincipalKind,
    ProjectApiKeyScope,
    ProjectMode,
    ProjectStatus,
    RateLimitIdentityKind,
    RuntimeClientKind,
    RuntimeScope,
)
from .models import (
    NormalizedEmail,
    OrganizationMembershipProjection,
    OrganizationProjection,
    ProjectId,
    UserProfileProjection,
)


@dataclass(frozen=True, slots=True)
class AnonymousPrincipal:
    principal_kind: Literal[PrincipalKind.ANONYMOUS] = PrincipalKind.ANONYMOUS
    credential_kind: Literal[CredentialKind.ANONYMOUS] = CredentialKind.ANONYMOUS


@dataclass(frozen=True, slots=True)
class UserPrincipal:
    subject_id: UUID
    email: NormalizedEmail
    email_verified: bool
    email_verification_source: EmailVerificationSource
    credential_kind: Literal[CredentialKind.SUPABASE_SESSION, CredentialKind.CLI_ACCESS]
    session_id: str | None
    assurance_level: AssuranceLevel
    authentication_methods: tuple[AuthenticationMethod, ...]
    issued_at: datetime | None
    expires_at: datetime | None
    email_verification_provider: OAuthProvider | None = None
    principal_kind: Literal[PrincipalKind.USER] = PrincipalKind.USER


@dataclass(frozen=True, slots=True)
class ProjectPrincipal:
    project_id: ProjectId
    api_key_id: UUID
    scope: ProjectApiKeyScope
    status: ApiKeyStatus
    expires_at: datetime | None
    credential_kind: Literal[CredentialKind.PROJECT_API_KEY] = CredentialKind.PROJECT_API_KEY
    principal_kind: Literal[PrincipalKind.PROJECT] = PrincipalKind.PROJECT


@dataclass(frozen=True, slots=True)
class RuntimePrincipal:
    project_id: ProjectId
    subject: str
    scopes: frozenset[RuntimeScope]
    issued_at: datetime
    expires_at: datetime
    request_id: str | None
    key_id: str
    actor_type: RuntimeClientKind | None = None
    organization_id: UUID | None = None
    credential_kind: Literal[CredentialKind.GATEWAY_RUNTIME_JWT] = (
        CredentialKind.GATEWAY_RUNTIME_JWT
    )
    principal_kind: Literal[PrincipalKind.RUNTIME] = PrincipalKind.RUNTIME


@dataclass(frozen=True, slots=True)
class DelegatedRuntimePrincipal:
    project_id: ProjectId
    subject: str
    scopes: frozenset[RuntimeScope]
    client_kind: RuntimeClientKind
    issued_at: datetime
    expires_at: datetime
    token_id: UUID
    key_id: str
    credential_kind: Literal[CredentialKind.DELEGATED_RUNTIME_JWT] = (
        CredentialKind.DELEGATED_RUNTIME_JWT
    )
    principal_kind: Literal[PrincipalKind.RUNTIME] = PrincipalKind.RUNTIME


@dataclass(frozen=True, slots=True)
class LegacyServicePrincipal:
    service_id: str
    scopes: tuple[str, ...]
    credential_kind: Literal[CredentialKind.LEGACY_DEMO_TOKEN] = CredentialKind.LEGACY_DEMO_TOKEN
    principal_kind: Literal[PrincipalKind.SERVICE] = PrincipalKind.SERVICE


AuthPrincipal = (
    AnonymousPrincipal
    | UserPrincipal
    | ProjectPrincipal
    | RuntimePrincipal
    | DelegatedRuntimePrincipal
    | LegacyServicePrincipal
)


@dataclass(frozen=True, slots=True)
class ProjectAccessRecord:
    project_id: ProjectId
    organization_id: UUID | None
    owner_subject_id: UUID | None
    status: ProjectStatus
    project_mode: ProjectMode = ProjectMode.STANDARD


@dataclass(frozen=True, slots=True)
class AdminAccess:
    principal: UserPrincipal
    profile: UserProfileProjection
    permissions: frozenset[Permission]


@dataclass(frozen=True, slots=True)
class OrganizationAccess:
    principal: UserPrincipal
    organization: OrganizationProjection
    membership: OrganizationMembershipProjection


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    principal: UserPrincipal | ProjectPrincipal
    project: ProjectAccessRecord
    permission: Permission
    organization_role: OrganizationRole | None


@dataclass(frozen=True, slots=True)
class RuntimeAccess:
    principal: RuntimePrincipal | DelegatedRuntimePrincipal | ProjectPrincipal
    project_id: ProjectId
    scope: RuntimeScope


AuthorizationCapability = AdminAccess | OrganizationAccess | ProjectAccess | RuntimeAccess


@dataclass(frozen=True, slots=True)
class OrganizationAuthResource:
    organization_id: UUID


@dataclass(frozen=True, slots=True)
class ProjectAuthResource:
    project_id: ProjectId


AuthResource = OrganizationAuthResource | ProjectAuthResource


@dataclass(frozen=True, slots=True)
class RateLimitContext:
    identity_kind: RateLimitIdentityKind
    client_ip: str | None = None
    subject_id: UUID | None = None
    project_id: ProjectId | None = None
    api_key_id: UUID | None = None
    runtime_subject: str | None = None
