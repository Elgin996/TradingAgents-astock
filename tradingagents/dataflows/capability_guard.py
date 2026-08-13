"""Runtime data-tool capability enforcement.

The guard deliberately lives above vendor routing: an unavailable capability
must fail before ``route_to_vendor`` can try an unrelated fallback provider.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Iterable


class CapabilityError(RuntimeError):
    """Raised when a data tool is unavailable for the active instrument."""


_active_capabilities: ContextVar[frozenset[str] | None] = ContextVar(
    "active_analysis_capabilities", default=None
)
_active_analysis_date: ContextVar[str | None] = ContextVar(
    "active_analysis_date", default=None
)

TOOL_CAPABILITIES: dict[str, str] = {
    "get_stock_data": "price_history",
    "get_index_data": "price_history",
    "get_indicators": "technical_indicators",
    "get_news": "index_news_policy",
    "get_global_news": "index_news_policy",
    "get_etf_profile": "fund_profile",
    "get_etf_shares_aum": "shares_and_aum",
    "get_etf_announcements": "index_news_policy",
    "get_etf_quote": "liquidity_metrics",
    "get_etf_peer_comparison": "peer_comparison",
    "get_etf_structure_alerts": "peer_comparison",
    "get_fundamentals": "company_financials",
    "get_balance_sheet": "company_financials",
    "get_cashflow": "company_financials",
    "get_income_statement": "company_financials",
    "get_profit_forecast": "profit_forecast",
    "get_insider_transactions": "insider_transactions",
    "get_dragon_tiger_board": "dragon_tiger_board",
    "get_lockup_expiry": "lockup_expiry",
    "get_industry_comparison": "company_competitive_moat",
    "get_fund_flow": "company_capital_flow",
    "get_concept_blocks": "company_competitive_moat",
    "get_hot_stocks": "market_breadth",
    "get_northbound_flow": "market_breadth",
}


def set_active_capabilities(capabilities: Iterable[str] | None):
    """Set active capabilities for the current analysis execution context."""
    return _active_capabilities.set(
        None if capabilities is None else frozenset(capabilities)
    )


def reset_active_capabilities(token) -> None:
    _active_capabilities.reset(token)


def set_active_analysis_date(trade_date: str | None):
    """Bind the authoritative date for model-invoked data tools."""
    return _active_analysis_date.set(str(trade_date) if trade_date else None)


def reset_active_analysis_date(token) -> None:
    _active_analysis_date.reset(token)


def analysis_date_for_tool(requested_date: str | None) -> str | None:
    """Prefer the graph's fixed date over a date supplied by the model."""
    return _active_analysis_date.get() or requested_date


def active_capabilities() -> frozenset[str] | None:
    """Return active capabilities for adapters that need mode-aware routing."""
    return _active_capabilities.get()


def assert_tool_allowed(method: str) -> None:
    """Fail closed when a recognized tool lacks an active capability."""
    capabilities = _active_capabilities.get()
    if capabilities is None:
        return  # Legacy/stock callers that do not opt into capability routing.
    capability = TOOL_CAPABILITIES.get(method)
    if capability is not None:
        from .analysis_capabilities import ETF_CAPABILITY_COMPATIBILITY_V2

        compatible = ETF_CAPABILITY_COMPATIBILITY_V2.get(capability)
        allowed = capability in capabilities or (
            compatible is not None and compatible in capabilities
        )
    else:
        allowed = True
    if not allowed:
        raise CapabilityError(
            f"工具 {method} 不适用于当前标的；缺少能力 {capability}。"
        )
