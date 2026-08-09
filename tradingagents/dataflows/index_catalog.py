"""Curated tracking-index code catalog for domestic equity ETF recognition.

Eastmoney fund profiles publish tracking-index *names* but not provider-qualified
codes. This table fills that gap for common indices with an auditable local
source label (``catalog``), so the UI can pre-fill codes without pretending the
code came from Eastmoney master data. Frozen historical tasks are never rewritten.
"""

from __future__ import annotations

import re

# Normalized index token -> (code, provider). Keep only codes that the project's
# A-share OHLCV loaders can route (6-digit SSE/SZSE index codes).
_INDEX_CATALOG: dict[str, tuple[str, str]] = {
    "沪深300": ("000300", "CSI"),
    "中证500": ("000905", "CSI"),
    "中证1000": ("000852", "CSI"),
    "中证800": ("000906", "CSI"),
    "中证A500": ("000510", "CSI"),
    "上证50": ("000016", "SSE"),
    "上证180": ("000010", "SSE"),
    "上证科创板50成份": ("000688", "SSE"),
    "科创50": ("000688", "SSE"),
    "科创板50": ("000688", "SSE"),
    "创业板": ("399006", "SZSE"),
    "创业板指": ("399006", "SZSE"),
    "深证成指": ("399001", "SZSE"),
    "深证成份": ("399001", "SZSE"),
    "中小板指": ("399005", "SZSE"),
    "中证银行": ("399986", "CSI"),
    "中证白酒": ("399997", "CSI"),
    "中证医药": ("399989", "CSI"),
    "中证红利": ("000922", "CSI"),
    "上证红利": ("000015", "SSE"),
}


def _provider_prefix(code: str, provider: str) -> str:
    if code.startswith("399") or provider == "SZSE":
        return "sz"
    return "sh"


# code -> sh/sz. Must stay in sync with catalog values (asserted in tests).
INDEX_EXCHANGE_BY_CODE: dict[str, str] = {
    code: _provider_prefix(code, provider)
    for code, provider in {pair for pair in _INDEX_CATALOG.values()}
}

_NOISE = re.compile(
    r"(价格指数|全收益指数|净收益指数|指数|收益率)$"
)
_PRICE_PAREN = re.compile(r"[（(]价格[)）]")


def normalize_tracking_index_name(name: str) -> str:
    """Collapse a fund-profile tracking label into a catalog lookup token."""
    text = name.strip()
    text = _PRICE_PAREN.sub("", text)
    text = _NOISE.sub("", text).strip()
    return text or name.strip()


def lookup_tracking_index_code(tracking_index_name: str | None) -> tuple[str, str] | None:
    """Return ``(code, provider)`` when the tracking-index name is in the catalog."""
    if not tracking_index_name:
        return None
    token = normalize_tracking_index_name(tracking_index_name)
    hit = _INDEX_CATALOG.get(token)
    if hit:
        return hit
    # Secondary pass: allow names that still contain a known catalog key.
    for key, value in _INDEX_CATALOG.items():
        if key and key in token:
            return value
    return None
