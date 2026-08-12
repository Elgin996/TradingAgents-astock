"""Backward-compatible façade for the strict v2 index master.

Older callers still import ``lookup_tracking_index_code``.  They now receive
the same exact-match behavior as the provider-qualified v2 directory; the
former substring fallback has intentionally been removed.
"""

from __future__ import annotations

from .index_master import (
    IndexCatalogRecord,
    load_index_catalog,
    lookup_index_by_code,
    match_index_name,
    normalize_index_name,
)


def normalize_tracking_index_name(name: str) -> str:
    return normalize_index_name(name)


def lookup_tracking_index_code(tracking_index_name: str | None) -> tuple[str, str] | None:
    matches = match_index_name(tracking_index_name)
    if len(matches) == 1:
        record = matches[0]
        return record.code, record.provider
    return None


def infer_tracking_index_provider(
    code: str, tracking_index_name: str | None = None
) -> str:
    """Infer a provider only from an exact directory code or explicit label.

    For an outside-directory code, the name prefix is retained as a clearly
    non-frozen attribution hint for legacy UI display.  It is not used by the
    v2 request builder to route an index series.
    """

    record = lookup_index_by_code(code)
    if record is not None:
        return record.provider
    name = (tracking_index_name or "").strip()
    for prefix, provider in (
        ("中证", "CSI"),
        ("上证", "SSE"),
        ("深证", "SZSE"),
        ("创业板", "SZSE"),
        ("国证", "CNI"),
    ):
        if prefix in name:
            return provider
    return "UNKNOWN"


_CATALOG = load_index_catalog()
INDEX_EXCHANGE_BY_CODE: dict[str, str] = {
    record.code: {"sh": "sh", "sz": "sz", "bj": "bj"}[record.exchange_route]
    for record in _CATALOG.records
}

# Legacy tests/integrations used this private mapping to inspect the catalog.
# Keep one canonical-name entry per record; aliases are resolved by the v2
# matcher and are intentionally not duplicated here.
_INDEX_CATALOG: dict[str, tuple[str, str]] = {
    record.name: (record.code, record.provider) for record in _CATALOG.records
}

# Kept for integrations that introspect the old module-level mapping.  It is
# generated from the versioned file rather than maintained independently.
INDEX_CATALOG: tuple[IndexCatalogRecord, ...] = _CATALOG.records
