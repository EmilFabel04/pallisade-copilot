"""
Stable ID generation and identifier normalization.

All IDs are deterministic: identical inputs always produce identical outputs.
"""

import hashlib
import re
from typing import Optional


def generate_asset_id(
    platform_domain: str,
    system: str,
    namespace: str,
    container: str,
    name: str,
) -> str:
    """
    Generate a stable asset ID from identity components.

    Uses SHA-256 truncated to 16 hex chars. The same inputs always
    produce the same output across runs.
    """
    key = f"{platform_domain}|{system}|{namespace}|{container}|{name}".lower()
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def generate_edge_id(
    from_id: str,
    to_id: str,
    edge_type: str,
    level: str,
    evidence_ref: str = "",
) -> str:
    """
    Generate a stable edge ID.

    Includes evidence_ref so that the same logical relationship
    discovered by different adapters gets separate edge IDs
    (they are later merged by the resolver).
    """
    key = f"{from_id}|{to_id}|{edge_type}|{level}|{evidence_ref}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# Characters to strip when normalizing identifiers
_QUOTE_CHARS = re.compile(r'[`"\[\]]')


def normalize_identifier(name: str, case_hint: str = "lower") -> str:
    """
    Normalize a SQL identifier by stripping quotes and applying casing.

    Args:
        name: Raw identifier (e.g., `"MyTable"`, `[dbo].[Users]`, `` `project.dataset.table` ``)
        case_hint: One of "lower", "upper", "preserve".
                   Adapters provide this based on their platform conventions.

    Returns:
        Normalized identifier string.
    """
    clean = _QUOTE_CHARS.sub("", name).strip()

    if case_hint == "lower":
        return clean.lower()
    elif case_hint == "upper":
        return clean.upper()
    return clean


def normalize_fqn(
    database: str,
    schema: str,
    name: str,
    case_hint: str = "lower",
    separator: str = ".",
) -> str:
    """
    Build a normalized fully-qualified name from parts.

    Skips empty parts so that ``normalize_fqn("", "public", "users")``
    returns ``"public.users"`` rather than ``".public.users"``.
    """
    parts = [
        normalize_identifier(p, case_hint)
        for p in [database, schema, name]
        if p
    ]
    return separator.join(parts)
