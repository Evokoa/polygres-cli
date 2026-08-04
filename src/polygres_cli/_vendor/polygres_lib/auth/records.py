from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from ..core.types import SecretValue
from .enums import (
    AssuranceLevel,
    AuthenticationMethod,
    CliCredentialStatus,
    CliLoginState,
    LegalAcceptanceMethod,
    RuntimeSyncStatus,
    SelfServiceAdmissionOutcome,
)
from .errors import AuthErrorCode
from .models import (
    AdminInvitationProjection,
    NormalizedEmail,
    OrganizationInvitationProjection,
    OrganizationMembershipProjection,
    OrganizationProjection,
    UserProfileProjection,
)


@dataclass(frozen=True, slots=True)
class EmailDeliveryResult:
    accepted: bool
    provider_message_id: str | None


@dataclass(frozen=True, slots=True)
class CurrentLegalAcceptance:
    terms_version: str
    privacy_version: str
    method: LegalAcceptanceMethod


@dataclass(frozen=True, slots=True)
class LegalAcceptanceReceipt:
    id: UUID
    user_id: UUID
    accepted_at: datetime
    terms_version: str
    privacy_version: str
    acceptance_method: LegalAcceptanceMethod


@dataclass(frozen=True, slots=True)
class AccountSetupMutationResult:
    profile: UserProfileProjection
    organization: OrganizationProjection | None
    membership: OrganizationMembershipProjection | None
    legal_receipt: LegalAcceptanceReceipt
    admin_invitation: AdminInvitationProjection | None
    admission_outcome: SelfServiceAdmissionOutcome | None


@dataclass(frozen=True, slots=True)
class OrganizationInvitationAcceptanceMutationResult:
    invitation: OrganizationInvitationProjection
    profile: UserProfileProjection
    membership: OrganizationMembershipProjection
    legal_receipt: LegalAcceptanceReceipt


@dataclass(frozen=True, slots=True)
class OrganizationInvitationSelectionMutationResult:
    selected_invitation_id: UUID
    verification_required: bool
    legal_receipt: LegalAcceptanceReceipt


@dataclass(frozen=True, slots=True, repr=False)
class GeneratedProjectApiKey:
    raw_key: SecretValue
    prefix: str
    sha256_hash: str


@dataclass(frozen=True, slots=True)
class RuntimeSyncResult:
    status: RuntimeSyncStatus
    version: int | None
    error_code: AuthErrorCode | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CliLoginSessionRecord:
    login_session_id: str
    state: CliLoginState
    poll_token_digest: str
    device_code_digest: str
    approved_subject_id: UUID | None
    approved_email: NormalizedEmail | None
    approved_session_id: str | None
    approved_authentication_methods: tuple[AuthenticationMethod, ...]
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CliCredentialRecord:
    credential_session_id: str
    subject_id: UUID
    email: NormalizedEmail
    email_verified: Literal[True]
    approval_session_id: str
    assurance_level: AssuranceLevel
    authentication_methods: tuple[AuthenticationMethod, ...]
    access_token_digest: str
    refresh_token_digest: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    status: CliCredentialStatus
