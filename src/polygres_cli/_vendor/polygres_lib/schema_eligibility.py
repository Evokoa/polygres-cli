"""Schema eligibility shared by application retrieval features.

Names are PostgreSQL catalog identities: comparisons are case-sensitive and
never normalize or rewrite an identifier. Identifier syntax is validated by
request contracts separately. PostgreSQL reserves the pg_ prefix.
"""

from __future__ import annotations

import re

EXCLUDED_SCHEMAS = (
    "pg_catalog",
    "information_schema",
    "polygres_runtime",
    "polygres_metadata",
    "graph",
    "pgcontext",
)


def is_eligible_schema(name: str) -> bool:
    return bool(name) and name not in EXCLUDED_SCHEMAS and not name.startswith("pg_")


def eligible_schema_sql(column: str) -> str:
    """Render a predicate for a trusted, qualified catalog column, never user SQL."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", column):
        raise ValueError("expected a qualified catalog column")
    excluded = ", ".join("'" + name + "'" for name in EXCLUDED_SCHEMAS)
    return f"({column} <> '' AND {column} NOT IN ({excluded}) AND {column} !~ '^pg_')"
