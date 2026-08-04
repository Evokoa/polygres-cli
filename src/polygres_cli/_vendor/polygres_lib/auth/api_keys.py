from __future__ import annotations

import hashlib
from uuid import UUID

from ..core.types import SecretCredential
from .enums import ApiKeyStatus, CredentialKind, RuntimeSyncKind, RuntimeSyncStatus
from .errors import AuthError, AuthErrorCode
from .models import (
    CreateProjectApiKeyRequest,
    CreateProjectApiKeyResponse,
    ProjectApiKeyResponse,
    ProjectApiKeysResponse,
    RuntimeSyncProjection,
)
from .ports import Clock, IdGenerator, ProjectApiKeyRepository, RuntimeApiKeySyncPort
from .principals import ProjectAccess, ProjectPrincipal
from .records import GeneratedProjectApiKey, RuntimeSyncResult
from .types import RequestContext


class ProjectApiKeyService:
    def __init__(
        self,
        *,
        repository: ProjectApiKeyRepository,
        sync: RuntimeApiKeySyncPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._runtime_sync = sync
        self._ids = ids
        self._clock = clock

    def generate_project_api_key(self) -> GeneratedProjectApiKey:
        entropy = self._ids.token_urlsafe(32)
        suffix = hashlib.sha256(entropy.encode("utf-8")).hexdigest()[:32]
        raw = SecretCredential(f"poly_live_{suffix}", kind_hint=CredentialKind.PROJECT_API_KEY)
        return GeneratedProjectApiKey(
            raw_key=raw,
            prefix=raw.reveal()[:18],
            sha256_hash=self.hash_project_api_key(raw),
        )

    @staticmethod
    def validate_project_api_key_format(raw_key: str) -> bool:
        import re

        return (
            isinstance(raw_key, str)
            and re.fullmatch(r"poly_live_[0-9a-f]{32}", raw_key) is not None
        )

    @classmethod
    def hash_project_api_key(cls, credential: SecretCredential) -> str:
        if not cls.validate_project_api_key_format(credential.reveal()):
            raise AuthError(AuthErrorCode.API_KEY_INVALID)
        return credential.sha256_hex()

    async def authenticate_project_api_key(
        self, *, credential: SecretCredential, project_id: str
    ) -> ProjectPrincipal:
        digest = self.hash_project_api_key(credential)
        metadata = await self._repository.find_active_by_hash(
            project_id=project_id, sha256_hash=digest
        )
        if metadata is None or metadata.status is not ApiKeyStatus.ACTIVE:
            raise AuthError(AuthErrorCode.API_KEY_INVALID)
        return ProjectPrincipal(
            project_id=metadata.project_id,
            api_key_id=metadata.id,
            scope=metadata.scope,
            status=metadata.status,
            expires_at=None,
        )

    async def list_project_api_keys(
        self, *, access: ProjectAccess, request_id: str
    ) -> ProjectApiKeysResponse:
        keys = await self._repository.list_for_project(access.project.project_id)
        return ProjectApiKeysResponse(request_id=request_id, api_keys=keys)

    async def create_project_api_key(
        self,
        *,
        access: ProjectAccess,
        command: CreateProjectApiKeyRequest,
        request: RequestContext,
    ) -> CreateProjectApiKeyResponse:
        generated = self.generate_project_api_key()
        metadata = await self._repository.create_pending(
            project_id=access.project.project_id,
            name=command.name,
            prefix=generated.prefix,
            sha256_hash=generated.sha256_hash,
            request=request,
        )
        sync = await self._synchronize(project_id=access.project.project_id)
        if sync.status is RuntimeSyncStatus.READY:
            metadata = await self._repository.mark_active(
                project_id=access.project.project_id,
                key_id=metadata.id,
                request=request,
            )
        return CreateProjectApiKeyResponse(
            request_id=request.request_id,
            api_key=metadata,
            raw_key=generated.raw_key,
            runtime_sync=_sync_projection(sync),
        )

    async def revoke_project_api_key(
        self,
        *,
        access: ProjectAccess,
        key_id: UUID,
        request: RequestContext,
    ) -> ProjectApiKeyResponse:
        metadata = await self._repository.revoke(
            project_id=access.project.project_id,
            key_id=key_id,
            request=request,
        )
        sync = await self._synchronize(project_id=access.project.project_id)
        return ProjectApiKeyResponse(
            request_id=request.request_id,
            api_key=metadata,
            runtime_sync=_sync_projection(sync),
        )

    async def _synchronize(self, *, project_id: str) -> RuntimeSyncResult:
        try:
            return await self._runtime_sync.sync_api_key_snapshot(project_id=project_id)
        except (AuthError, OSError, TimeoutError):
            return RuntimeSyncResult(
                status=RuntimeSyncStatus.DEGRADED,
                version=None,
                error_code=AuthErrorCode.RUNTIME_API_KEY_SNAPSHOT_UNAVAILABLE,
                updated_at=self._clock.now(),
            )


def _sync_projection(result: RuntimeSyncResult) -> RuntimeSyncProjection:
    return RuntimeSyncProjection(
        kind=RuntimeSyncKind.API_KEYS,
        status=result.status,
        version=result.version or 0,
        error_code=result.error_code,
        updated_at=result.updated_at,
    )
