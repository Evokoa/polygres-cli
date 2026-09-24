"""Project lifecycle values shared by control-plane and Runtime clients."""
from enum import Enum

from .errors import PolygresError, catalog_error


class ProjectArchiveState(str, Enum):
    ACTIVE = "active"
    ARCHIVING = "archiving"
    ARCHIVED = "archived"
    RESTORING = "restoring"


def project_archive_blocks_access(state: str | None) -> bool:
    # Unknown values fail closed during rolling upgrades.
    return state is not None and state != ProjectArchiveState.ACTIVE


def project_archive_error(state: str) -> PolygresError:
    """Return the canonical lifecycle error without interpreting unknown states as active."""
    variant = state if state in {"archiving", "archived", "restoring"} else None
    return catalog_error("PROJECT_ARCHIVED", variant=variant, details={"archive_state": state})
