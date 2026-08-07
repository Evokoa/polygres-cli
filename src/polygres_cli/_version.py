"""Installed Polygres CLI distribution version."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("polygres-cli")
except PackageNotFoundError:
    # Source archives may be imported before installation. This value is
    # intentionally not a valid release version and must never ship in headers.
    __version__ = "0+unknown"

__all__ = ["__version__"]
