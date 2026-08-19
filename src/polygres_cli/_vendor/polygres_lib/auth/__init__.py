"""Generated private auth subset. Do not edit by hand."""

from ..core.types import SecretCredential
from .api_keys import ProjectApiKeyService
from .errors import (
    AUTH_ERROR_CATALOG,
    AuthError,
    AuthErrorCode,
    AuthErrorDescriptor,
    PolygresError,
)
from .models import (
    CliClientInfo,
    CliLoginPollApproved,
    CliLoginPollRequest,
    CliLoginPollResponse,
    CliLoginStartRequest,
    CliLoginStartResponse,
    CliSessionRefreshRequest,
    CliSessionRefreshResponse,
    CliSessionRevokeRequest,
)

__all__ = [
    "AUTH_ERROR_CATALOG",
    "AuthError",
    "AuthErrorCode",
    "AuthErrorDescriptor",
    "CliClientInfo",
    "CliLoginPollApproved",
    "CliLoginPollRequest",
    "CliLoginPollResponse",
    "CliLoginStartRequest",
    "CliLoginStartResponse",
    "CliSessionRefreshRequest",
    "CliSessionRefreshResponse",
    "CliSessionRevokeRequest",
    "PolygresError",
    "ProjectApiKeyService",
    "SecretCredential",
]
