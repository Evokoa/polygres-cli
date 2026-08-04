from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AfterValidator, Field, TypeAdapter, field_validator, model_validator

from ..core.models import StrictContractModel
from ..core.types import SecretCredential
from .enums import (
    AccountGate,
    AdminInvitationBillingStatus,
    AdminInvitationState,
    ApiKeyStatus,
    ApprovalStatus,
    AssuranceLevel,
    AuthenticationMethod,
    AuthFlow,
    AuthIntentRedirectClass,
    BillingStatus,
    CliLoginState,
    CredentialKind,
    EmailActionType,
    EmailContentMode,
    IdentitySurface,
    InvitationAction,
    InvitationBatchItemState,
    InvitationBlockedReason,
    InvitationKind,
    LifecycleState,
    OrganizationInvitationDeliveryStatus,
    OrganizationInvitationRole,
    OrganizationInvitationState,
    OrganizationMembershipStatus,
    OrganizationRole,
    Permission,
    PermissionCheckKind,
    PolicyDecisionReason,
    ProjectApiKeyScope,
    ReservedTopLevelOrganizationSlug,
    RuntimeSyncKind,
    RuntimeSyncStatus,
    UserType,
)
from .errors import AuthErrorCode

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PROJECT_ID_PATTERN = re.compile(r"^p[a-z0-9]{23}$")
ORGANIZATION_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("email must be a string")
    normalized = value.strip().lower()
    if not 3 <= len(normalized) <= 320 or EMAIL_PATTERN.fullmatch(normalized) is None:
        raise ValueError("invalid email")
    return normalized


def normalize_human_text(value: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError("text must be a string")
    if not isinstance(max_length, int) or max_length < 1:
        raise ValueError("max_length must be positive")
    normalized = " ".join(value.strip().split())
    if not normalized or len(normalized) > max_length:
        raise ValueError(f"text must contain 1..{max_length} characters")
    return normalized


def normalize_optional_human_text(value: str | None, max_length: int) -> str | None:
    return None if value is None else normalize_human_text(value, max_length)


NormalizedEmail = Annotated[str, AfterValidator(normalize_email)]
DisplayName = Annotated[str, AfterValidator(lambda value: normalize_human_text(value, 80))]
OrganizationName = Annotated[str, AfterValidator(lambda value: normalize_human_text(value, 120))]


def _validate_project_id(value: str) -> str:
    if not isinstance(value, str) or PROJECT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid project ID")
    return value


def _validate_organization_slug(value: str) -> str:
    if not isinstance(value, str) or ORGANIZATION_SLUG_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid organization slug")
    if value in {item.value for item in ReservedTopLevelOrganizationSlug}:
        raise ValueError("reserved organization slug")
    return value


def _validate_request_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or not value.isascii()
        or not value.isprintable()
    ):
        raise ValueError("request ID must contain 1..128 printable ASCII characters")
    return value


ProjectId = Annotated[str, AfterValidator(_validate_project_id)]
OrganizationSlug = Annotated[str, AfterValidator(_validate_organization_slug)]
RequestId = Annotated[str, AfterValidator(_validate_request_id)]


class LegalAcceptanceInput(StrictContractModel):
    accepted: Literal[True]


class AccountSetupCommand(StrictContractModel):
    display_name: DisplayName | None
    organization_name: OrganizationName | None
    admin_invitation_id: UUID | None
    legal_acceptance: LegalAcceptanceInput | None = None

    @field_validator("legal_acceptance", mode="before")
    @classmethod
    def _reject_explicit_null_legal_acceptance(
        cls, value: object
    ) -> object:
        if value is None:
            raise ValueError("legal acceptance must be omitted or explicitly accepted")
        return value


class LegalAcceptanceResponse(StrictContractModel):
    request_id: RequestId
    has_accepted_current_legal: Literal[True]


class UserProfileProjection(StrictContractModel):
    subject_id: UUID
    email: NormalizedEmail
    display_name: DisplayName | None
    lifecycle_state: LifecycleState
    approval_status: ApprovalStatus
    billing_status: BillingStatus
    assigned_tier_id: str | None
    user_type: UserType
    discount_applied: float = Field(ge=0, allow_inf_nan=False)
    rejected_reason: str | None = Field(default=None, max_length=1000)
    suspended_reason: str | None = Field(default=None, max_length=1000)
    default_organization_name: OrganizationName | None

    @field_validator("assigned_tier_id")
    @classmethod
    def _normalize_tier(cls, value: str | None) -> str | None:
        return normalize_optional_human_text(value, 80)


class UserIdentityProjection(StrictContractModel):
    subject_id: UUID
    email: NormalizedEmail
    email_verified: bool
    credential_kind: CredentialKind
    assurance_level: AssuranceLevel
    authentication_methods: tuple[AuthenticationMethod, ...]


class OrganizationProjection(StrictContractModel):
    id: UUID
    name: OrganizationName
    slug: OrganizationSlug
    billing_status: BillingStatus
    assigned_tier_id: str | None
    created_by: UUID

    @field_validator("assigned_tier_id")
    @classmethod
    def _normalize_tier(cls, value: str | None) -> str | None:
        return normalize_optional_human_text(value, 80)


class OrganizationMembershipProjection(StrictContractModel):
    organization_id: UUID
    subject_id: UUID
    role: OrganizationRole
    status: OrganizationMembershipStatus
    invited_by: UUID | None
    display_name: DisplayName | None
    email: NormalizedEmail | None


class CurrentOrganizationProjection(StrictContractModel):
    id: UUID
    name: OrganizationName
    slug: OrganizationSlug


class OrganizationPendingInvitation(StrictContractModel):
    kind: Literal[InvitationKind.ORGANIZATION] = InvitationKind.ORGANIZATION
    id: UUID
    email: NormalizedEmail
    organization_id: UUID
    organization_name: OrganizationName
    role: OrganizationInvitationRole
    state: Literal[OrganizationInvitationState.PENDING] = OrganizationInvitationState.PENDING
    expires_at: datetime
    blocked_reason: InvitationBlockedReason | None
    current_organization: CurrentOrganizationProjection | None
    permitted_actions: tuple[InvitationAction, ...]

    @model_validator(mode="after")
    def _validate_blocked_state(self) -> OrganizationPendingInvitation:
        blocked = (
            self.blocked_reason is InvitationBlockedReason.ORGANIZATION_MEMBERSHIP_LIMIT_EXCEEDED
        )
        if blocked != (self.current_organization is not None):
            raise ValueError("blocked organization invitations require current organization")
        if len(set(self.permitted_actions)) != len(self.permitted_actions):
            raise ValueError("permitted actions must be unique")
        return self


class AdminPendingInvitation(StrictContractModel):
    kind: Literal[InvitationKind.ADMIN] = InvitationKind.ADMIN
    id: UUID
    email: NormalizedEmail
    display_name: DisplayName | None
    organization_id: UUID | None
    organization_name: OrganizationName | None
    billing_status: AdminInvitationBillingStatus
    assigned_tier_id: str = Field(min_length=1, max_length=80)
    state: Literal[AdminInvitationState.PENDING] = AdminInvitationState.PENDING
    expires_at: datetime
    blocked_reason: InvitationBlockedReason | None
    permitted_actions: tuple[InvitationAction, ...]

    @field_validator("assigned_tier_id")
    @classmethod
    def _normalize_assigned_tier(cls, value: str) -> str:
        return normalize_human_text(value, 80)

    @model_validator(mode="after")
    def _validate_actions(self) -> AdminPendingInvitation:
        if len(set(self.permitted_actions)) != len(self.permitted_actions):
            raise ValueError("permitted actions must be unique")
        return self


PendingInvitationProjection = Annotated[
    OrganizationPendingInvitation | AdminPendingInvitation,
    Field(discriminator="kind"),
]


def build_identity_scope(
    *,
    subject_id: UUID,
    surface: IdentitySurface,
    organization_id: UUID | None,
) -> str:
    organization = str(organization_id) if organization_id is not None else "none"
    raw = f"v1\0user\0{subject_id}\0{surface.value}\0{organization}".encode()
    digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
    return f"scope_v1_{digest}"


class AuthContext(StrictContractModel):
    identity: UserIdentityProjection
    profile: UserProfileProjection | None
    organization: OrganizationProjection | None
    membership: OrganizationMembershipProjection | None
    has_accepted_current_legal: bool
    account_gate: AccountGate
    effective_permissions: tuple[Permission, ...]
    project_count: int = Field(ge=0)
    pending_invitations: tuple[PendingInvitationProjection, ...]
    pending_invitation_count: int = Field(ge=0)
    identity_scope: str = Field(pattern=r"^scope_v1_[A-Za-z0-9_-]{43}$")

    @model_validator(mode="after")
    def _count_matches(self) -> AuthContext:
        if self.pending_invitation_count != len(self.pending_invitations):
            raise ValueError("pending_invitation_count must match pending_invitations")
        if (
            tuple(sorted(set(self.effective_permissions), key=lambda item: item.value))
            != self.effective_permissions
        ):
            raise ValueError("effective permissions must be sorted and unique")
        return self


class AuthContextResponse(StrictContractModel):
    request_id: RequestId
    auth_context: AuthContext


class VerificationRequestedResponse(StrictContractModel):
    request_id: RequestId
    sent: bool


class EmailVerificationCompletionCommand(StrictContractModel):
    evidence: SecretCredential

    @field_validator("evidence")
    @classmethod
    def _bounded_evidence(cls, value: SecretCredential) -> SecretCredential:
        compact = value.reveal()
        if len(compact) > 1536 or compact.count(".") != 2:
            raise ValueError("email verification evidence is invalid")
        return value


class EmailVerificationCompletionResponse(StrictContractModel):
    request_id: RequestId
    email_verified: Literal[True]


class AuthIntent(StrictContractModel):
    version: Literal[1] = 1
    issuer: Literal["polygres-auth"] = "polygres-auth"
    audience: str
    flow: Literal[AuthFlow.ORGANIZATION_INVITATION, AuthFlow.ADMIN_INVITATION]
    email_action_type: Literal[EmailActionType.INVITE, EmailActionType.EMAIL] = (
        EmailActionType.EMAIL
    )
    invitation_kind: InvitationKind
    invitation_id: UUID
    redirect_class: AuthIntentRedirectClass
    issued_at: int
    expires_at: int
    key_id: str = Field(min_length=1, max_length=64)

    @field_validator("audience")
    @classmethod
    def _absolute_audience(cls, value: str) -> str:
        parsed = urlsplit(value)
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback))
        ):
            raise ValueError("Auth intent audience must be an absolute HTTPS origin")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _binding_matches(self) -> AuthIntent:
        expected = {
            InvitationKind.ORGANIZATION: (
                AuthFlow.ORGANIZATION_INVITATION,
                AuthIntentRedirectClass.ORGANIZATION_INVITATION_REVIEW,
            ),
            InvitationKind.ADMIN: (
                AuthFlow.ADMIN_INVITATION,
                AuthIntentRedirectClass.ADMIN_INVITATION_SETUP,
            ),
        }[self.invitation_kind]
        if (self.flow, self.redirect_class) != expected:
            raise ValueError("Auth intent flow and redirect class must match invitation kind")
        if (
            self.invitation_kind is InvitationKind.ADMIN
            and self.email_action_type is not EmailActionType.EMAIL
        ):
            raise ValueError("Admin invitation intents must use the email action type")
        if self.expires_at <= self.issued_at:
            raise ValueError("Auth intent expiry must follow issue time")
        return self


class EmptyRequest(StrictContractModel):
    pass


class LegalAcceptanceProjection(StrictContractModel):
    terms_version: str = Field(min_length=1, max_length=128)
    privacy_version: str = Field(min_length=1, max_length=128)
    accepted_at: datetime


class AccountSetupResponse(StrictContractModel):
    request_id: RequestId
    auth_context: AuthContext
    legal_acceptance: LegalAcceptanceProjection


class PendingInvitationsResponse(StrictContractModel):
    request_id: RequestId
    invitations: tuple[PendingInvitationProjection, ...]


class OrganizationInvitationProjection(StrictContractModel):
    id: UUID
    organization_id: UUID
    organization_name: OrganizationName
    email: NormalizedEmail
    role: OrganizationInvitationRole
    state: OrganizationInvitationState
    delivery_status: OrganizationInvitationDeliveryStatus
    delivery_retryable: bool
    delivery_started_at: datetime | None
    invited_by: UUID
    expires_at: datetime
    accepted_by: UUID | None
    accepted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CreateOrganizationInvitationRequest(StrictContractModel):
    email: NormalizedEmail
    role: OrganizationInvitationRole


class AcceptOrganizationInvitationRequest(StrictContractModel):
    legal_acceptance: LegalAcceptanceInput | None = None

    @field_validator("legal_acceptance", mode="before")
    @classmethod
    def _reject_explicit_null_legal_acceptance(cls, value: object) -> object:
        if value is None:
            raise ValueError("legal_acceptance must be omitted or an acknowledgement")
        return value


class SelectOrganizationInvitationRequest(StrictContractModel):
    invitation_id: UUID
    legal_acceptance: LegalAcceptanceInput | None = None

    @field_validator("legal_acceptance", mode="before")
    @classmethod
    def _reject_explicit_null_legal_acceptance(cls, value: object) -> object:
        if value is None:
            raise ValueError("legal_acceptance must be omitted or an acknowledgement")
        return value


class OrganizationInvitationsResponse(StrictContractModel):
    request_id: RequestId
    invitations: tuple[OrganizationInvitationProjection, ...]


class OrganizationInvitationResponse(StrictContractModel):
    request_id: RequestId
    invitation: OrganizationInvitationProjection


class AcceptOrganizationInvitationResponse(StrictContractModel):
    request_id: RequestId
    membership: OrganizationMembershipProjection
    legal_acceptance: LegalAcceptanceProjection


class SelectOrganizationInvitationResponse(StrictContractModel):
    request_id: RequestId
    selected_invitation_id: UUID
    verification_required: bool
    legal_acceptance: LegalAcceptanceProjection


class CancelOrganizationInvitationSelectionResponse(StrictContractModel):
    request_id: RequestId
    declined_invitation_count: int = Field(ge=0)


class RolePermissionCheck(StrictContractModel):
    kind: Literal[PermissionCheckKind.ORGANIZATION_ROLE] = PermissionCheckKind.ORGANIZATION_ROLE
    organization_id: UUID
    roles: tuple[OrganizationRole, ...] = Field(min_length=1, max_length=4)

    @field_validator("roles")
    @classmethod
    def _unique_roles(cls, value: tuple[OrganizationRole, ...]) -> tuple[OrganizationRole, ...]:
        if len(set(value)) != len(value):
            raise ValueError("roles must be unique")
        return value


_PROJECT_PERMISSIONS = frozenset(Permission) - {Permission.PLATFORM_ADMIN_ACCESS}


class ProjectPermissionCheck(StrictContractModel):
    kind: Literal[PermissionCheckKind.PROJECT_PERMISSION] = PermissionCheckKind.PROJECT_PERMISSION
    project_id: ProjectId
    permission: Permission

    @field_validator("permission")
    @classmethod
    def _project_permission(cls, value: Permission) -> Permission:
        if value not in _PROJECT_PERMISSIONS:
            raise ValueError("permission is not project-scoped")
        return value


class ApplicationPermissionCheck(StrictContractModel):
    kind: Literal[PermissionCheckKind.APPLICATION_PERMISSION] = (
        PermissionCheckKind.APPLICATION_PERMISSION
    )
    permission: Literal[Permission.PLATFORM_ADMIN_ACCESS] = Permission.PLATFORM_ADMIN_ACCESS


PermissionCheck = Annotated[
    RolePermissionCheck | ProjectPermissionCheck | ApplicationPermissionCheck,
    Field(discriminator="kind"),
]


class PermissionCheckRequest(StrictContractModel):
    checks: tuple[PermissionCheck, ...] = Field(min_length=1, max_length=50)


class PermissionCheckItemResult(StrictContractModel):
    allowed: bool
    reason: PolicyDecisionReason | None

    @model_validator(mode="after")
    def _reason_matches(self) -> PermissionCheckItemResult:
        if self.allowed != (self.reason is None):
            raise ValueError("allowed checks omit a reason; denied checks require one")
        return self


class PermissionCheckResponse(StrictContractModel):
    request_id: RequestId
    allowed: bool
    checks: tuple[PermissionCheckItemResult, ...]

    @model_validator(mode="after")
    def _aggregate_matches(self) -> PermissionCheckResponse:
        if self.allowed != all(item.allowed for item in self.checks):
            raise ValueError("allowed must equal all check results")
        return self


class AdminAuthContext(StrictContractModel):
    subject_id: UUID
    email: NormalizedEmail
    display_name: DisplayName | None
    lifecycle_state: Literal[LifecycleState.ACTIVE] = LifecycleState.ACTIVE
    approval_status: Literal[ApprovalStatus.ACTIVE] = ApprovalStatus.ACTIVE
    user_type: Literal[UserType.ADMIN] = UserType.ADMIN
    permissions: tuple[Literal[Permission.PLATFORM_ADMIN_ACCESS]] = (
        Permission.PLATFORM_ADMIN_ACCESS,
    )


class AdminAuthContextResponse(StrictContractModel):
    request_id: RequestId
    admin_context: AdminAuthContext


class AdminInvitationListQuery(StrictContractModel):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CreateAdminInvitationRequest(StrictContractModel):
    email: NormalizedEmail
    display_name: DisplayName | None
    organization_name: OrganizationName | None
    billing_status: AdminInvitationBillingStatus = AdminInvitationBillingStatus.BETA
    tier_id: str

    @field_validator("tier_id")
    @classmethod
    def _tier(cls, value: str) -> str:
        return normalize_human_text(value, 80)


class AdminInvitationBatchRecipient(StrictContractModel):
    email: NormalizedEmail
    display_name: DisplayName | None
    organization_name: OrganizationName | None


_PLACEHOLDER_PATTERN = re.compile(r"{{[^{}]+}}")


class CreateAdminInvitationBatchRequest(StrictContractModel):
    dry_run: bool = False
    recipients: tuple[AdminInvitationBatchRecipient, ...] = Field(min_length=1, max_length=100)
    subject: str
    body: str
    mode: EmailContentMode = EmailContentMode.TEXT
    billing_status: AdminInvitationBillingStatus = AdminInvitationBillingStatus.BETA
    tier_id: str

    @field_validator("subject")
    @classmethod
    def _subject(cls, value: str) -> str:
        normalized = normalize_human_text(value, 200)
        if any(
            character in value for character in ("\r", "\n", "\v", "\f", "\x85", "\u2028", "\u2029")
        ):
            raise ValueError("email subject cannot contain line separators")
        return normalized

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("email body must be a string")
        normalized = value.strip()
        if not 1 <= len(normalized) <= 20_000:
            raise ValueError("email body must contain 1..20000 characters")
        placeholders = _PLACEHOLDER_PATTERN.findall(normalized)
        if "{{invite_link}}" not in placeholders or set(placeholders) != {"{{invite_link}}"}:
            raise ValueError("email body must contain only the invite_link placeholder")
        return normalized

    @field_validator("tier_id")
    @classmethod
    def _batch_tier(cls, value: str) -> str:
        return normalize_human_text(value, 80)

    @model_validator(mode="after")
    def _unique_recipients(self) -> CreateAdminInvitationBatchRequest:
        emails = [recipient.email for recipient in self.recipients]
        if len(set(emails)) != len(emails):
            raise ValueError("recipient emails must be unique after normalization")
        return self


class AdminInvitationProjection(StrictContractModel):
    id: UUID
    email: NormalizedEmail
    display_name: DisplayName | None
    organization_name: OrganizationName | None
    organization_id: UUID | None
    subject_id: UUID | None
    billing_status: AdminInvitationBillingStatus
    assigned_tier_id: str
    state: AdminInvitationState
    invited_by: UUID
    failure_reason: str | None = Field(max_length=1000)
    expires_at: datetime
    sent_at: datetime | None
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator("assigned_tier_id")
    @classmethod
    def _projection_tier(cls, value: str) -> str:
        return normalize_human_text(value, 80)


class AdminInvitationBatchItemResult(StrictContractModel):
    email: NormalizedEmail
    display_name: DisplayName | None
    organization_name: OrganizationName | None
    state: InvitationBatchItemState
    invitation_id: UUID | None
    provider_message_id: str | None
    error_code: AuthErrorCode | None

    @model_validator(mode="after")
    def _state_shape(self) -> AdminInvitationBatchItemResult:
        if self.state is InvitationBatchItemState.DRY_RUN:
            valid = self.invitation_id is self.provider_message_id is self.error_code is None
        elif self.state is InvitationBatchItemState.SENT:
            valid = self.invitation_id is not None and self.error_code is None
        else:
            valid = self.error_code is not None and self.provider_message_id is None
        if not valid:
            raise ValueError("batch item fields do not match state")
        return self


class AdminInvitationsResponse(StrictContractModel):
    request_id: RequestId
    invitations: tuple[AdminInvitationProjection, ...]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AdminInvitationResponse(StrictContractModel):
    request_id: RequestId
    invitation: AdminInvitationProjection


class AdminInvitationBatchResponse(StrictContractModel):
    request_id: RequestId
    dry_run: bool
    items: tuple[AdminInvitationBatchItemResult, ...]
    sent_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts_match(self) -> AdminInvitationBatchResponse:
        if self.dry_run:
            valid = self.sent_count == self.failed_count == 0 and all(
                item.state is InvitationBatchItemState.DRY_RUN for item in self.items
            )
        else:
            valid = self.sent_count + self.failed_count == len(self.items)
        if not valid:
            raise ValueError("batch counts do not match item states")
        return self


class RuntimeSyncProjection(StrictContractModel):
    kind: Literal[RuntimeSyncKind.API_KEYS] = RuntimeSyncKind.API_KEYS
    status: RuntimeSyncStatus
    version: int = Field(ge=0)
    error_code: AuthErrorCode | None
    updated_at: datetime | None

    @model_validator(mode="after")
    def _sync_error_matches(self) -> RuntimeSyncProjection:
        if self.status is RuntimeSyncStatus.READY and self.error_code is not None:
            raise ValueError("ready runtime sync cannot have an error")
        if self.status is RuntimeSyncStatus.DEGRADED and self.error_code is None:
            raise ValueError("degraded runtime sync requires an error")
        return self


class ProjectApiKeyMetadata(StrictContractModel):
    id: UUID
    project_id: ProjectId
    name: str
    prefix: str = Field(pattern=r"^poly_live_[0-9a-f]{8}$")
    status: ApiKeyStatus
    scope: ProjectApiKeyScope
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @field_validator("name")
    @classmethod
    def _api_key_name(cls, value: str) -> str:
        return normalize_human_text(value, 80)


class CreateProjectApiKeyRequest(StrictContractModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return normalize_human_text(value, 80)


class ProjectApiKeysResponse(StrictContractModel):
    request_id: RequestId
    api_keys: tuple[ProjectApiKeyMetadata, ...]


class ProjectApiKeyResponse(StrictContractModel):
    request_id: RequestId
    api_key: ProjectApiKeyMetadata
    runtime_sync: RuntimeSyncProjection


def _secret_pattern(
    value: SecretCredential, pattern: re.Pattern[str], name: str
) -> SecretCredential:
    if pattern.fullmatch(value.reveal()) is None:
        raise ValueError(f"invalid {name}")
    return value


_CLI_LOGIN_SESSION_ID = re.compile(r"^cls_[A-Za-z0-9_-]{20,128}$")
_CLI_POLL_TOKEN = re.compile(r"^pcli_poll_[A-Za-z0-9_-]{32,128}$")
_CLI_ACCESS_TOKEN = re.compile(r"^pcli_at_[A-Za-z0-9_-]{32,128}$")
_CLI_REFRESH_TOKEN = re.compile(r"^pcli_rt_[A-Za-z0-9_-]{32,128}$")
_DEVICE_CODE = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{4}$")
_SIGNED_CLI_STATE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


class CliClientInfo(StrictContractModel):
    name: Literal["polygres-cli"] = "polygres-cli"
    version: str = Field(min_length=1, max_length=64)


class CliLoginStartRequest(StrictContractModel):
    client: CliClientInfo


class CliUserProjection(StrictContractModel):
    subject_id: UUID
    email: NormalizedEmail


class CliTokenPair(StrictContractModel):
    access_token: SecretCredential
    refresh_token: SecretCredential
    access_expires_at: datetime
    refresh_expires_at: datetime
    user: CliUserProjection

    @field_validator("access_token")
    @classmethod
    def _access_token(cls, value: SecretCredential) -> SecretCredential:
        return _secret_pattern(value, _CLI_ACCESS_TOKEN, "CLI access token")

    @field_validator("refresh_token")
    @classmethod
    def _refresh_token(cls, value: SecretCredential) -> SecretCredential:
        return _secret_pattern(value, _CLI_REFRESH_TOKEN, "CLI refresh token")


class CliLoginStartResponse(StrictContractModel):
    request_id: RequestId
    login_session_id: str = Field(pattern=_CLI_LOGIN_SESSION_ID.pattern)
    browser_url: str
    poll_token: SecretCredential
    device_code: str = Field(pattern=_DEVICE_CODE.pattern)
    expires_at: datetime
    poll_interval_seconds: int = Field(ge=1)

    @field_validator("browser_url")
    @classmethod
    def _browser_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if not parsed.netloc or (
            parsed.scheme != "https" and not (parsed.scheme == "http" and loopback)
        ):
            raise ValueError("browser URL must be absolute HTTPS or loopback HTTP")
        return value

    @field_validator("poll_token")
    @classmethod
    def _poll_token(cls, value: SecretCredential) -> SecretCredential:
        return _secret_pattern(value, _CLI_POLL_TOKEN, "CLI poll token")


class CliLoginPollRequest(StrictContractModel):
    login_session_id: str = Field(pattern=_CLI_LOGIN_SESSION_ID.pattern)
    poll_token: SecretCredential | None
    device_code: str | None = Field(pattern=_DEVICE_CODE.pattern)

    @field_validator("poll_token")
    @classmethod
    def _optional_poll_token(cls, value: SecretCredential | None) -> SecretCredential | None:
        return None if value is None else _secret_pattern(value, _CLI_POLL_TOKEN, "CLI poll token")

    @model_validator(mode="after")
    def _one_possession_method(self) -> CliLoginPollRequest:
        if (self.poll_token is None) == (self.device_code is None):
            raise ValueError("exactly one CLI poll possession method is required")
        return self


class CliLoginPollPending(StrictContractModel):
    state: Literal[CliLoginState.PENDING] = CliLoginState.PENDING
    poll_interval_seconds: int = Field(ge=1)


class CliLoginPollApproved(StrictContractModel):
    state: Literal[CliLoginState.APPROVED] = CliLoginState.APPROVED
    token_pair: CliTokenPair


class CliLoginPollDenied(StrictContractModel):
    state: Literal[CliLoginState.DENIED] = CliLoginState.DENIED


class CliLoginPollExpired(StrictContractModel):
    state: Literal[CliLoginState.EXPIRED] = CliLoginState.EXPIRED


class CliLoginPollConsumed(StrictContractModel):
    state: Literal[CliLoginState.CONSUMED] = CliLoginState.CONSUMED


CliLoginPollResult = Annotated[
    CliLoginPollPending
    | CliLoginPollApproved
    | CliLoginPollDenied
    | CliLoginPollExpired
    | CliLoginPollConsumed,
    Field(discriminator="state"),
]


class CliLoginPollResponse(StrictContractModel):
    request_id: RequestId
    result: CliLoginPollResult


class CliBrowserDecisionRequest(StrictContractModel):
    browser_state: SecretCredential

    @field_validator("browser_state")
    @classmethod
    def _browser_state(cls, value: SecretCredential) -> SecretCredential:
        if len(value.reveal()) > 1024:
            raise ValueError("signed CLI browser state is too long")
        return _secret_pattern(value, _SIGNED_CLI_STATE, "signed CLI browser state")


class CliLoginApproveRequest(CliBrowserDecisionRequest):
    pass


class CliLoginDenyRequest(CliBrowserDecisionRequest):
    pass


class CliLoginActionResponse(StrictContractModel):
    request_id: RequestId
    login_session_id: str = Field(pattern=_CLI_LOGIN_SESSION_ID.pattern)
    state: Literal[CliLoginState.APPROVED, CliLoginState.DENIED]


class CliSessionRefreshRequest(StrictContractModel):
    refresh_token: SecretCredential

    @field_validator("refresh_token")
    @classmethod
    def _refresh(cls, value: SecretCredential) -> SecretCredential:
        return _secret_pattern(value, _CLI_REFRESH_TOKEN, "CLI refresh token")


class CliSessionRevokeRequest(CliSessionRefreshRequest):
    pass


class CliSessionRefreshResponse(StrictContractModel):
    request_id: RequestId
    token_pair: CliTokenPair


class CliSessionRevokeResponse(StrictContractModel):
    request_id: RequestId
    revoked: bool


class CreateProjectApiKeyResponse(StrictContractModel):
    request_id: RequestId
    api_key: ProjectApiKeyMetadata
    raw_key: SecretCredential
    runtime_sync: RuntimeSyncProjection

    @field_validator("raw_key")
    @classmethod
    def _raw_key(cls, value: SecretCredential) -> SecretCredential:
        return _secret_pattern(value, re.compile(r"^poly_live_[0-9a-f]{32}$"), "project API key")


PUBLIC_MODEL_TYPES = (
    EmptyRequest,
    AuthContextResponse,
    VerificationRequestedResponse,
    EmailVerificationCompletionCommand,
    EmailVerificationCompletionResponse,
    AccountSetupCommand,
    LegalAcceptanceResponse,
    AccountSetupResponse,
    PendingInvitationsResponse,
    PermissionCheckRequest,
    PermissionCheckResponse,
    CreateOrganizationInvitationRequest,
    AcceptOrganizationInvitationRequest,
    SelectOrganizationInvitationRequest,
    OrganizationInvitationsResponse,
    OrganizationInvitationResponse,
    AcceptOrganizationInvitationResponse,
    SelectOrganizationInvitationResponse,
    CancelOrganizationInvitationSelectionResponse,
    AdminAuthContextResponse,
    AdminInvitationListQuery,
    CreateAdminInvitationRequest,
    CreateAdminInvitationBatchRequest,
    AdminInvitationsResponse,
    AdminInvitationResponse,
    AdminInvitationBatchResponse,
    CreateProjectApiKeyRequest,
    ProjectApiKeysResponse,
    ProjectApiKeyResponse,
    CliLoginStartRequest,
    CliLoginStartResponse,
    CliLoginPollRequest,
    CliLoginPollResponse,
    CliLoginApproveRequest,
    CliLoginDenyRequest,
    CliLoginActionResponse,
    CliSessionRefreshRequest,
    CliSessionRevokeRequest,
    CliSessionRefreshResponse,
    CliSessionRevokeResponse,
    CreateProjectApiKeyResponse,
)

PendingInvitationAdapter = TypeAdapter(PendingInvitationProjection)

__all__ = [
    name
    for name, value in globals().items()
    if isinstance(value, type) and value.__module__ == __name__ and not name.startswith("_")
] + [
    "DisplayName",
    "NormalizedEmail",
    "OrganizationName",
    "OrganizationSlug",
    "PendingInvitationProjection",
    "CliLoginPollResult",
    "PermissionCheck",
    "ProjectId",
    "RequestId",
    "build_identity_scope",
    "normalize_email",
    "normalize_human_text",
    "normalize_optional_human_text",
]
