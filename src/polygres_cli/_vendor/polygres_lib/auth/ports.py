from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .enums import (
    AuthAuditEventType,
    CliLoginState,
    CliRefreshOutcome,
    OrganizationInvitationRole,
)
from .models import (
    AccountSetupCommand,
    AdminInvitationProjection,
    CreateAdminInvitationRequest,
    NormalizedEmail,
    OrganizationInvitationProjection,
    OrganizationMembershipProjection,
    OrganizationProjection,
    PendingInvitationProjection,
    ProjectApiKeyMetadata,
    UserProfileProjection,
)
from .principals import OrganizationAccess, ProjectAccessRecord, RateLimitContext, UserPrincipal
from .records import (
    AccountSetupMutationResult,
    CliCredentialRecord,
    CliLoginSessionRecord,
    CurrentLegalAcceptance,
    EmailDeliveryResult,
    OrganizationInvitationAcceptanceMutationResult,
    OrganizationInvitationSelectionMutationResult,
    RuntimeSyncResult,
)
from .types import RequestContext

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class IdGenerator(Protocol):
    def uuid4(self) -> UUID: ...

    def token_urlsafe(self, nbytes: int) -> str: ...


class AuditSink(Protocol):
    async def append(
        self,
        *,
        event_type: AuthAuditEventType,
        actor_subject_id: UUID | None,
        request_id: str,
        payload: Mapping[str, JsonValue],
    ) -> None: ...


class EmailSender(Protocol):
    async def send(
        self,
        *,
        template: str,
        recipient: NormalizedEmail,
        payload: Mapping[str, JsonValue],
    ) -> EmailDeliveryResult: ...


class RateLimiter(Protocol):
    async def require(self, *, rule_id: str, context: RateLimitContext, now: datetime) -> None: ...

    async def record_auth_failure(
        self, *, rule_id: str, context: RateLimitContext, now: datetime
    ) -> None: ...

    async def clear_auth_failures(self, *, rule_id: str, context: RateLimitContext) -> None: ...


class AccountReadRepository(Protocol):
    async def get_profile(self, subject_id: UUID) -> UserProfileProjection | None: ...

    async def is_email_verified(self, subject_id: UUID) -> bool: ...

    async def has_accepted_current_legal(self, subject_id: UUID) -> bool: ...

    async def is_self_service_admission_pending(self, subject_id: UUID) -> bool: ...

    async def get_current_membership(
        self, subject_id: UUID
    ) -> OrganizationMembershipProjection | None: ...

    async def get_organization(self, organization_id: UUID) -> OrganizationProjection | None: ...

    async def count_projects(self, subject_id: UUID) -> int: ...


class ProjectAuthorizationRepository(Protocol):
    async def get_project_access_record(self, project_id: str) -> ProjectAccessRecord | None: ...

    async def get_membership_for_project(
        self, *, subject_id: UUID, project_id: str
    ) -> OrganizationMembershipProjection | None: ...


class InvitationReadRepository(Protocol):
    async def is_email_verified(self, subject_id: UUID) -> bool: ...

    async def has_pending_organization_invitation_selection(
        self, *, subject_id: UUID, email: str
    ) -> bool: ...

    async def list_pending_for_recipient(
        self,
        *,
        subject_id: UUID,
        email: NormalizedEmail,
        organization_invitation_id: UUID | None = None,
    ) -> tuple[PendingInvitationProjection, ...]: ...

    async def list_organization_pending(
        self, organization_id: UUID
    ) -> tuple[OrganizationInvitationProjection, ...]: ...

    async def get_organization_invitation(
        self, invitation_id: UUID
    ) -> OrganizationInvitationProjection | None: ...

    async def get_admin_invitation(
        self, invitation_id: UUID
    ) -> AdminInvitationProjection | None: ...

    async def list_admin_invitations(
        self, *, limit: int = 25, offset: int = 0
    ) -> tuple[AdminInvitationProjection, ...]: ...

    async def count_admin_invitations(self) -> int: ...


class AtomicAuthMutationRepository(Protocol):
    async def setup_account_atomic(
        self,
        *,
        principal: UserPrincipal,
        command: AccountSetupCommand,
        legal: CurrentLegalAcceptance,
        request: RequestContext,
    ) -> AccountSetupMutationResult: ...

    async def accept_organization_invitation_atomic(
        self,
        *,
        principal: UserPrincipal,
        invitation_id: UUID,
        legal: CurrentLegalAcceptance,
        request: RequestContext,
    ) -> OrganizationInvitationAcceptanceMutationResult: ...

    async def select_organization_invitation_atomic(
        self,
        *,
        principal: UserPrincipal,
        invitation_id: UUID,
        legal: CurrentLegalAcceptance,
        request: RequestContext,
    ) -> OrganizationInvitationSelectionMutationResult: ...

    async def cancel_organization_invitation_selection_atomic(
        self,
        *,
        principal: UserPrincipal,
        request: RequestContext,
    ) -> int: ...


class InvitationMutationRepository(Protocol):
    async def create_organization_invitation(
        self,
        *,
        organization: OrganizationAccess,
        email: NormalizedEmail,
        role: OrganizationInvitationRole,
        expires_at: datetime,
        request: RequestContext,
    ) -> OrganizationInvitationProjection: ...

    async def mark_organization_invitation_sent(
        self, *, invitation_id: UUID, sent_at: datetime
    ) -> OrganizationInvitationProjection: ...

    async def revoke_organization_invitation(
        self,
        *,
        organization: OrganizationAccess,
        invitation_id: UUID,
        request: RequestContext,
    ) -> OrganizationInvitationProjection: ...

    async def decline_organization_invitation(
        self,
        *,
        principal: UserPrincipal,
        invitation_id: UUID,
        request: RequestContext,
    ) -> OrganizationInvitationProjection: ...

    async def create_admin_invitation(
        self,
        *,
        admin: object,
        command: CreateAdminInvitationRequest,
        request: RequestContext,
    ) -> AdminInvitationProjection: ...

    async def update_admin_invitation_delivery(
        self,
        *,
        invitation_id: UUID,
        accepted: bool,
        provider_message_id: str | None,
        request: RequestContext,
    ) -> AdminInvitationProjection: ...


class CliAuthStore(Protocol):
    async def create_login_session(self, record: CliLoginSessionRecord) -> None: ...

    async def get_login_session(self, session_id: str) -> CliLoginSessionRecord | None: ...

    async def approve_login_session(
        self, *, session_id: str, principal: UserPrincipal, now: datetime
    ) -> CliLoginState: ...

    async def deny_login_session(self, *, session_id: str, now: datetime) -> CliLoginState: ...

    async def consume_approved_login(
        self,
        *,
        session_id: str,
        possession_digest: str,
        credentials: CliCredentialRecord,
        now: datetime,
    ) -> bool: ...

    async def resolve_access_token(
        self, *, token_digest: str, now: datetime
    ) -> CliCredentialRecord | None: ...

    async def resolve_refresh_token(
        self, *, token_digest: str, now: datetime
    ) -> CliCredentialRecord | None: ...

    async def rotate_refresh_token(
        self,
        *,
        current_digest: str,
        replacement: CliCredentialRecord,
        now: datetime,
    ) -> CliRefreshOutcome: ...

    async def revoke_refresh_token(self, *, token_digest: str, now: datetime) -> bool: ...

    async def ready(self) -> bool: ...


class ProjectApiKeyRepository(Protocol):
    async def find_active_by_hash(
        self, *, project_id: str, sha256_hash: str
    ) -> ProjectApiKeyMetadata | None: ...

    async def list_for_project(self, project_id: str) -> tuple[ProjectApiKeyMetadata, ...]: ...

    async def create_pending(
        self,
        *,
        project_id: str,
        name: str,
        prefix: str,
        sha256_hash: str,
        request: RequestContext,
    ) -> ProjectApiKeyMetadata: ...

    async def mark_active(
        self, *, project_id: str, key_id: UUID, request: RequestContext
    ) -> ProjectApiKeyMetadata: ...

    async def revoke(
        self, *, project_id: str, key_id: UUID, request: RequestContext
    ) -> ProjectApiKeyMetadata: ...


class RuntimeApiKeySyncPort(Protocol):
    async def sync_api_key_snapshot(self, *, project_id: str) -> RuntimeSyncResult: ...

    async def reconcile_project_api_key_sync(self, *, project_id: str) -> RuntimeSyncResult: ...
