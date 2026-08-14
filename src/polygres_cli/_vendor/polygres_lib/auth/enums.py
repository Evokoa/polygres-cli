from enum import Enum, IntEnum


class CredentialKind(str, Enum):
    SUPABASE_SESSION = "supabase_session"
    CLI_ACCESS = "cli_access"
    CLI_POLL = "cli_poll"
    CLI_REFRESH = "cli_refresh"
    PROJECT_API_KEY = "project_api_key"
    GATEWAY_RUNTIME_JWT = "gateway_runtime_jwt"
    DELEGATED_RUNTIME_JWT = "delegated_runtime_jwt"
    LEGACY_DEMO_TOKEN = "legacy_demo_token"
    ANONYMOUS = "anonymous"


class PrincipalKind(str, Enum):
    USER = "user"
    PROJECT = "project"
    RUNTIME = "runtime"
    SERVICE = "service"
    ANONYMOUS = "anonymous"


class SessionResolutionKind(str, Enum):
    VALID = "valid"
    NO_SESSION = "no_session"
    TERMINAL_LOCAL_SESSION = "terminal_local_session"
    DEPENDENCY_FAILURE = "dependency_failure"


class CredentialLocation(str, Enum):
    NONE = "none"
    AUTHORIZATION_HEADER = "authorization_header"
    REQUEST_BODY = "request_body"
    HTTP_ONLY_COOKIE = "http_only_cookie"


class IdentitySurface(str, Enum):
    PORTAL = "portal"
    ADMIN = "admin"


class SessionFailureKind(str, Enum):
    MALFORMED_AUTH_COOKIE = "malformed_auth_cookie"
    INCOMPLETE_CHUNKED_AUTH_COOKIE = "incomplete_chunked_auth_cookie"
    INVALID_ACCESS_TOKEN = "invalid_access_token"
    REFRESH_TOKEN_NOT_FOUND = "refresh_token_not_found"
    REFRESH_TOKEN_ALREADY_USED = "refresh_token_already_used"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_EXPIRED = "session_expired"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    CONFIGURATION_UNAVAILABLE = "configuration_unavailable"


class AssuranceLevel(str, Enum):
    AAL1 = "aal1"


class EmailVerificationSource(str, Enum):
    CONFIGURED_SIGNED_CLAIM = "configured_signed_claim"
    PROVIDER_USER = "provider_user"
    DASHBOARD_APPROVAL = "dashboard_approval"
    NONE = "none"


class AuthenticationMethod(str, Enum):
    PASSWORD = "password"
    OTP = "otp"
    MAGIC_LINK = "magic_link"
    OAUTH = "oauth"
    INVITE = "invite"
    EMAIL_SIGNUP = "email_signup"
    RECOVERY = "recovery"
    UNKNOWN = "unknown"


class OAuthProvider(str, Enum):
    GOOGLE = "google"
    GITHUB = "github"


class LogoutScope(str, Enum):
    LOCAL = "local"
    GLOBAL = "global"


class PasswordChangeMode(str, Enum):
    RECENT_OR_NONCE = "recent_or_nonce"
    CURRENT_PASSWORD = "current_password"


class PasswordOperation(str, Enum):
    SET_PASSWORD = "set_password"
    CHANGE_PASSWORD = "change_password"
    RECOVER_PASSWORD = "recover_password"


class PasswordRequirement(str, Enum):
    LENGTH = "length"
    CHARACTERS = "characters"
    PWNED = "pwned"


class AuthChangeEvent(str, Enum):
    INITIAL_SESSION = "initial_session"
    SIGNED_IN = "signed_in"
    SIGNED_OUT = "signed_out"
    TOKEN_REFRESHED = "token_refreshed"
    USER_UPDATED = "user_updated"
    PASSWORD_RECOVERY = "password_recovery"


class ApprovalStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class SelfServiceAdmissionOutcome(str, Enum):
    ADMITTED = "admitted"
    ALREADY_ADMITTED = "already_admitted"
    DISABLED = "disabled"


class LifecycleState(str, Enum):
    REGISTERED_UNVERIFIED = "registered_unverified"
    NEEDS_EMAIL_VERIFICATION = "needs_email_verification"
    REGISTERED_VERIFIED = "registered_verified"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class BillingStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BETA = "beta"


class AdminInvitationBillingStatus(str, Enum):
    ACTIVE = "active"
    BETA = "beta"


class UserType(str, Enum):
    STANDARD = "standard"
    DESIGN_PARTNER = "design_partner"
    ADMIN = "admin"


class AccountGate(str, Enum):
    EMAIL_VERIFICATION_REQUIRED = "email_verification_required"
    ADMIN_INVITATION_REVIEW = "admin_invitation_review"
    ORGANIZATION_INVITATION_REVIEW = "organization_invitation_review"
    ACCOUNT_SETUP_REQUIRED = "account_setup_required"
    APPROVAL_PENDING = "approval_pending"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    ACTIVE = "active"


class OrganizationRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class OrganizationInvitationRole(str, Enum):
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class OrganizationMembershipStatus(str, Enum):
    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"


class ReservedTopLevelOrganizationSlug(str, Enum):
    ACCOUNT = "account"
    API = "api"
    AUTH = "auth"
    CLI = "cli"
    INVITE = "invite"
    LOGIN = "login"
    ONBOARDING = "onboarding"
    PENDING = "pending"
    PROJECTS = "projects"
    REJECTED = "rejected"
    SIGNUP = "signup"
    SUSPENDED = "suspended"
    VERIFY_EMAIL = "verify-email"


class Permission(str, Enum):
    PLATFORM_ADMIN_ACCESS = "platform:admin:access"
    PROJECT_CREATE = "project:create"
    PROJECT_READ = "project:read"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"
    PROJECT_SQL_EXECUTE = "project:sql:execute"
    PROJECT_RETRY_PROVISIONING = "project:retry_provisioning"
    IMPORTS_READ = "imports:read"
    IMPORTS_MANAGE = "imports:manage"
    MIGRATIONS_READ = "migrations:read"
    MIGRATIONS_MANAGE = "migrations:manage"
    GRAPH_READ = "graph:read"
    GRAPH_MANAGE = "graph:manage"
    VECTOR_READ = "vector:read"
    VECTOR_MANAGE = "vector:manage"
    TEXT_READ = "text:read"
    TEXT_MANAGE = "text:manage"
    CONTEXT_READ = "context:read"
    CONTEXT_MANAGE = "context:manage"
    RUNTIME_READ = "runtime:read"


class RuntimeScope(str, Enum):
    GRAPH_READ = "graph:read"
    GRAPH_MANAGE = "graph:manage"
    VECTOR_READ = "vector:read"
    VECTOR_MANAGE = "vector:manage"
    TEXT_READ = "text:read"
    TEXT_MANAGE = "text:manage"
    RETRIEVAL_READ = "retrieval:read"
    HYBRID_READ = "hybrid:read"
    CONTEXT_READ = "context:read"
    CONTEXT_MANAGE = "context:manage"
    ROWS_WRITE = "rows:write"


class RuntimeClientKind(str, Enum):
    DASHBOARD = "dashboard"
    CLI = "cli"
    GATEWAY_SYSTEM = "gateway_system"


class ProjectApiKeyScope(str, Enum):
    PROJECT_FULL = "project_full"


class PermissionCheckKind(str, Enum):
    ORGANIZATION_ROLE = "organization_role"
    PROJECT_PERMISSION = "project_permission"
    APPLICATION_PERMISSION = "application_permission"


class PolicyDecisionReason(str, Enum):
    ALLOWED = "allowed"
    AUTHENTICATION_REQUIRED = "authentication_required"
    CREDENTIAL_NOT_ALLOWED = "credential_not_allowed"
    EMAIL_VERIFICATION_REQUIRED = "email_verification_required"
    ACCOUNT_STATE_DENIED = "account_state_denied"
    PERMISSION_DENIED = "permission_denied"
    RESOURCE_CONCEALED = "resource_concealed"
    DEPENDENCY_FAILURE = "dependency_failure"


class ResourceConcealment(str, Enum):
    NONE = "none"
    NOT_FOUND = "not_found"


class JwtAlgorithm(str, Enum):
    HS256 = "HS256"
    RS256 = "RS256"
    ES256 = "ES256"


class ProjectStatus(str, Enum):
    PROVISIONING = "provisioning"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"
    SUSPENDED = "suspended"
    READ_ONLY = "read_only"


class RateLimitIdentityKind(str, Enum):
    ANONYMOUS = "anonymous"
    SUPABASE_USER = "supabase_user"
    CLI_USER = "cli_user"
    PROJECT_API_KEY = "project_api_key"
    ADMIN_OPERATOR = "admin_operator"
    GATEWAY_RUNTIME = "gateway_runtime"
    LEGACY_SERVICE = "legacy_service"


class RateLimitScope(str, Enum):
    IP = "ip"
    PSEUDONYMOUS_SUBJECT = "pseudonymous_subject"
    USER = "user"
    USER_PROJECT = "user_project"
    PROJECT = "project"
    API_KEY = "api_key"
    ADMIN = "admin"
    AUTH_FAILURE = "auth_failure"


class RateLimitStorageFailureMode(str, Enum):
    FAIL_CLOSED = "fail_closed"
    FAIL_OPEN_READ_ONLY = "fail_open_read_only"


class ProjectGuard(str, Enum):
    NONE = "none"
    PERSONAL_OWNER_OR_ORGANIZATION_ADMIN = "personal_owner_or_organization_admin"


class ResourceExtractorId(str, Enum):
    NONE = "none"
    PRINCIPAL_ACTIVE_ORGANIZATION = "principal_active_organization"
    PERMISSION_CHECK_REQUEST = "permission_check_request"
    AUTHENTICATED_IDENTITY_INVITATIONS = "authenticated_identity_invitations"
    BODY_OPTIONAL_ADMIN_INVITATION = "body_optional_admin_invitation"
    PATH_ORGANIZATION = "path_organization"
    PATH_IDENTITY_INVITATION = "path_identity_invitation"
    PATH_ORGANIZATION_INVITATION = "path_organization_invitation"
    PATH_ADMIN_INVITATION = "path_admin_invitation"
    BODY_CLI_POLL_POSSESSION = "body_cli_poll_possession"
    BODY_SIGNED_CLI_BROWSER_STATE = "body_signed_cli_browser_state"
    BODY_CLI_REFRESH_TOKEN = "body_cli_refresh_token"
    QUERY_SIGNED_CLI_BROWSER_STATE = "query_signed_cli_browser_state"
    SIGNED_EMAIL_ACTION_CONTEXT = "signed_email_action_context"
    PATH_PROJECT = "path_project"
    PATH_PROJECT_API_KEY = "path_project_api_key"
    PATH_PROJECT_JOB = "path_project_job"
    PATH_PROJECT_TABLE = "path_project_table"
    PATH_PROJECT_IMPORT = "path_project_import"
    PATH_PROJECT_MIGRATION = "path_project_migration"
    PATH_PROJECT_CONFIGURATION = "path_project_configuration"
    PATH_ORGANIZATION_SUBJECT = "path_organization_subject"
    PATH_ROADMAP_ITEM = "path_roadmap_item"
    PATH_ADMIN_SUBJECT = "path_admin_subject"
    PATH_ADMIN_UUID_RESOURCE = "path_admin_uuid_resource"
    PATH_ADMIN_RUNTIME_VERSION = "path_admin_runtime_version"
    HOST_PROJECT = "host_project"
    HOST_PROJECT_CONFIGURATION = "host_project_configuration"


class RateLimitPhase(str, Enum):
    PRE_AUTH = "pre_auth"
    POST_AUTH = "post_auth"


class PolicyId(str, Enum):
    PUBLIC = "public"
    PUBLIC_AUTH_CALLBACK = "public_auth_callback"
    PUBLIC_CLI_CALLBACK = "public_cli_callback"
    PUBLIC_EMAIL_ACTION = "public_email_action"
    PUBLIC_SESSION_RECOVERY = "public_session_recovery"
    PORTAL_SESSION = "portal_session"
    DASHBOARD_ONLY = "dashboard_only"
    DASHBOARD_OR_CLI = "dashboard_or_cli"
    ACTIVE_ACCOUNT = "active_account"
    ADMIN_OPERATOR = "admin_operator"
    ORGANIZATION_MEMBER = "organization_member"
    ORGANIZATION_ADMIN = "organization_admin"
    PROJECT_PERMISSION = "project_permission"
    PROJECT_API_KEY = "project_api_key"
    GATEWAY_RUNTIME = "gateway_runtime"
    RUNTIME_ROW_WRITE = "runtime_row_write"
    CLI_FLOW = "cli_flow"
    RECOVERY_SESSION = "recovery_session"
    LEGACY_DEMO = "legacy_demo"


class InvitationKind(str, Enum):
    ORGANIZATION = "organization"
    ADMIN = "admin"


class OrganizationInvitationState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXPIRED = "expired"


class OrganizationInvitationDeliveryStatus(str, Enum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class AdminInvitationState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"
    FAILED = "failed"


class InvitationAction(str, Enum):
    ACCEPT = "accept"
    DECLINE = "decline"
    COMPLETE_ACCOUNT_SETUP = "complete_account_setup"
    SWITCH_ACCOUNT = "switch_account"
    RETURN_TO_CURRENT_ORGANIZATION = "return_to_current_organization"


class InvitationBlockedReason(str, Enum):
    ORGANIZATION_MEMBERSHIP_LIMIT_EXCEEDED = "organization_membership_limit_exceeded"
    INVITATION_ACCOUNT_MISMATCH = "invitation_account_mismatch"
    ACCOUNT_NOT_ELIGIBLE = "account_not_eligible"


class EmailActionType(str, Enum):
    SIGNUP = "signup"
    INVITE = "invite"
    EMAIL = "email"
    OAUTH_GOOGLE = "oauth_google"
    OAUTH_GITHUB = "oauth_github"
    RECOVERY = "recovery"


class SupabaseGenerateLinkType(str, Enum):
    MAGICLINK = "magiclink"


class SupabaseProviderVerificationType(str, Enum):
    MAGICLINK = "magiclink"
    SIGNUP = "signup"


class AuthFlow(str, Enum):
    PASSWORD_SIGN_IN = "password_sign_in"
    PASSWORD_SIGN_UP = "password_sign_up"
    MAGIC_LINK_SIGN_IN = "magic_link_sign_in"
    MAGIC_LINK_SIGN_UP = "magic_link_sign_up"
    OAUTH_PKCE = "oauth_pkce"
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RECOVERY = "password_recovery"
    ORGANIZATION_INVITATION = "organization_invitation"
    ADMIN_INVITATION = "admin_invitation"
    CLI_BROWSER = "cli_browser"


class AuthIntentRedirectClass(str, Enum):
    ORGANIZATION_INVITATION_REVIEW = "organization_invitation_review"
    ADMIN_INVITATION_SETUP = "admin_invitation_setup"


class EmailActionRoutingClass(str, Enum):
    ACCOUNT_GATE = "account_gate"
    PROJECT_CREATION = "project_creation"
    ORGANIZATION_INVITATION_REVIEW = "organization_invitation_review"
    ADMIN_INVITATION_SETUP = "admin_invitation_setup"
    PASSWORD_RECOVERY = "password_recovery"
    CLI_BROWSER = "cli_browser"


class LegalAcceptanceMethod(str, Enum):
    EXPLICIT_ACCEPT_BUTTON = "explicit_accept_button"


class EmailContentMode(str, Enum):
    TEXT = "text"
    HTML = "html"


class AuthEmailTemplate(str, Enum):
    ORGANIZATION_INVITATION = "organization_invitation"
    ADMIN_INVITATION = "admin_invitation"
    ADMIN_INVITATION_CUSTOM = "admin_invitation_custom"


class InvitationBatchItemState(str, Enum):
    DRY_RUN = "dry_run"
    SENT = "sent"
    FAILED = "failed"


class CliPollCredentialKind(str, Enum):
    POLL_TOKEN = "poll_token"
    DEVICE_CODE = "device_code"


class CliLoginState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class CliCredentialStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class CliRefreshOutcome(str, Enum):
    ROTATED = "rotated"
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ApiKeyStatus(str, Enum):
    ACTIVE = "active"
    PENDING_SYNC = "pending_sync"
    REVOKED = "revoked"


class RuntimeSyncKind(str, Enum):
    API_KEYS = "api_keys"


class RuntimeSyncStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    DEGRADED = "degraded"


class AuthAuditEventType(str, Enum):
    EMAIL_VERIFICATION_REQUESTED = "email_verification_requested"
    ACCOUNT_SETUP_COMPLETED = "account_setup_completed"
    ORGANIZATION_INVITATION_CREATE = "organization_invitation_create"
    ORGANIZATION_INVITATION_ACCEPT = "organization_invitation_accept"
    ORGANIZATION_INVITATION_DECLINE = "organization_invitation_decline"
    ORGANIZATION_INVITATION_REVOKE = "organization_invitation_revoke"
    ORGANIZATION_INVITATION_RESEND = "organization_invitation_resend"
    ADMIN_USER_INVITATION_CREATE = "admin_user_invitation_create"
    ADMIN_USER_INVITATION_BATCH_CREATE = "admin_user_invitation_batch_create"
    ADMIN_USER_INVITATION_RESEND = "admin_user_invitation_resend"
    ADMIN_USER_INVITATION_ACCEPTED = "admin_user_invitation_accepted"
    CLI_AUTH_START = "cli_auth_start"
    CLI_AUTH_APPROVE = "cli_auth_approve"
    CLI_AUTH_DENY = "cli_auth_deny"
    CLI_AUTH_REFRESH = "cli_auth_refresh"
    CLI_AUTH_REVOKE = "cli_auth_revoke"
    AUTH_SESSION_LOGOUT = "auth_session_logout"
    AUTH_SESSION_RESET = "auth_session_reset"
    API_KEY_CREATE = "api_key_create"
    API_KEY_REVOKE = "api_key_revoke"


class RetryClass(str, Enum):
    NEVER = "never"
    USER_RETRY = "user_retry"
    BOUNDED_RETRY = "bounded_retry"
    DEPENDENCY_RETRY = "dependency_retry"


class ResetClass(str, Enum):
    NONE = "none"
    LOCAL_SESSION = "local_session"
    EXPLICIT_LOGOUT = "explicit_logout"


class CliExitCode(IntEnum):
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


__all__ = [
    name
    for name, value in globals().items()
    if (
        isinstance(value, type)
        and issubclass(value, (Enum, IntEnum))
        and value.__module__ == __name__
    )
]
