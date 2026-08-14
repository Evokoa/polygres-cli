from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .generated import ERROR_CATALOG_DATA


@dataclass(frozen=True, slots=True)
class ErrorVariantDescriptor:
    message: str
    http_status: int


@dataclass(frozen=True, slots=True)
class ErrorDescriptor:
    code: str
    family: str
    category: str
    kinds: frozenset[str]
    visibility: str
    http_status: int
    message: str
    message_key: str
    safe_detail_fields: frozenset[str]
    retry_class: str
    reset_class: str
    cli_exit_code: int
    variants: Mapping[str, ErrorVariantDescriptor]


def _build_catalog() -> Mapping[str, ErrorDescriptor]:
    catalog: dict[str, ErrorDescriptor] = {}
    for row in ERROR_CATALOG_DATA:
        variants = MappingProxyType(
            {
                name: ErrorVariantDescriptor(
                    message=value["message"],
                    http_status=value["http_status"],
                )
                for name, value in row["variants"].items()
            }
        )
        descriptor = ErrorDescriptor(
            code=row["code"],
            family=row["family"],
            category=row["category"],
            kinds=frozenset(row["kind"]),
            visibility=row["visibility"],
            http_status=row["http_status"],
            message=row["message"],
            message_key=row["message_key"],
            safe_detail_fields=frozenset(row["safe_detail_fields"]),
            retry_class=row["retry_class"],
            reset_class=row["reset_class"],
            cli_exit_code=row["cli_exit_code"],
            variants=variants,
        )
        catalog[descriptor.code] = descriptor
    return MappingProxyType(catalog)


ERROR_CATALOG = _build_catalog()


def render_error(code: str, *, variant: str | None = None) -> tuple[str, int]:
    """Return catalog-owned user copy and HTTP status for an error identity."""
    try:
        descriptor = ERROR_CATALOG[code]
    except KeyError as exc:
        raise ValueError(f"unknown error code: {code}") from exc
    if variant is None:
        return descriptor.message, descriptor.http_status
    try:
        selected = descriptor.variants[variant]
    except KeyError as exc:
        raise ValueError(f"unknown error variant: {code}/{variant}") from exc
    return selected.message, selected.http_status


def catalog_message(code: str, *, variant: str | None = None) -> str:
    return render_error(code, variant=variant)[0]


def _safe_details(
    descriptor: ErrorDescriptor,
    details: Mapping[str, object] | None,
) -> dict[str, object]:
    supplied = dict(details or {})
    unknown = supplied.keys() - descriptor.safe_detail_fields
    if unknown:
        raise ValueError(f"unsafe error detail keys for {descriptor.code}: {sorted(unknown)!r}")
    return supplied


@dataclass(frozen=True, slots=True)
class CatalogErrorRecord:
    code: str
    variant: str | None
    message: str
    http_status: int
    details: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "variant": self.variant,
            "message": self.message,
            "http_status": self.http_status,
            "details": dict(self.details),
        }


def error_record(
    code: str,
    *,
    variant: str | None = None,
    details: Mapping[str, object] | None = None,
) -> CatalogErrorRecord:
    try:
        descriptor = ERROR_CATALOG[code]
    except KeyError as exc:
        raise ValueError(f"unknown error code: {code}") from exc
    message, status_code = render_error(code, variant=variant)
    return CatalogErrorRecord(
        code=code,
        variant=variant,
        message=message,
        http_status=status_code,
        details=MappingProxyType(_safe_details(descriptor, details)),
    )


def error_record_or_fallback(
    code: object,
    *,
    fallback_code: str,
    variant: object = None,
    details: Mapping[str, object] | None = None,
) -> CatalogErrorRecord:
    """Resolve untrusted or historical error identity through the catalog."""
    if isinstance(code, str) and code in ERROR_CATALOG:
        selected_variant = variant if isinstance(variant, str) else None
        try:
            return error_record(code, variant=selected_variant, details=details)
        except ValueError:
            pass
    return error_record(fallback_code)


def error_record_from_exception(
    error: BaseException,
    *,
    fallback_code: str,
    fallback_variant: str | None = None,
) -> CatalogErrorRecord:
    """Map a caught exception to a safe, catalog-owned error record.

    Catalog-backed exceptions preserve their identity. Other exceptions are
    collapsed to the caller-selected fallback so exception class names and
    dependency prose cannot become persisted or public contracts.
    """
    if isinstance(error, PolygresError):
        return error_record(
            error.code,
            variant=error.variant,
            details=error.details,
        )
    return error_record(fallback_code, variant=fallback_variant)


class PolygresError(Exception):
    """Catalog-backed public API error.

    Construct instances with :func:`catalog_error`. The legacy positional
    ``PolygresError(code, message, status_code=...)`` API does not exist.
    """

    def __init__(self, record: CatalogErrorRecord) -> None:
        if not isinstance(record, CatalogErrorRecord):
            raise TypeError("PolygresError must be created from a catalog error record")
        super().__init__(record.message)
        self.code = record.code
        self.variant = record.variant
        self.message = record.message
        self.status_code = record.http_status
        self.details = dict(record.details)
        descriptor = ERROR_CATALOG[record.code]
        self.retry_class = descriptor.retry_class
        self.reset_class = descriptor.reset_class
        self.message_key = descriptor.message_key

    def __repr__(self) -> str:
        identity = self.code if self.variant is None else f"{self.code}/{self.variant}"
        return f"PolygresError({identity!r})"


def catalog_error(
    code: str,
    *,
    variant: str | None = None,
    details: Mapping[str, object] | None = None,
) -> PolygresError:
    return PolygresError(error_record(code, variant=variant, details=details))
