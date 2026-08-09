"""LangChain tools exposed only to ETF analysts."""

from typing import Annotated
from langchain_core.tools import tool
from .core_stock_tools import route_to_vendor
from tradingagents.dataflows.capability_guard import assert_tool_allowed


@tool
def get_etf_profile(symbol: Annotated[str, "6-digit ETF code"]) -> str:
    """Fetch ETF identity, manager, tracking index, and fee disclosures."""
    assert_tool_allowed("get_etf_profile")
    return route_to_vendor("get_etf_profile", symbol)


@tool
def get_etf_quote(symbol: Annotated[str, "6-digit ETF code"]) -> str:
    """Fetch an ETF quote snapshot with published turnover."""
    assert_tool_allowed("get_etf_quote")
    return route_to_vendor("get_etf_quote", symbol)


@tool
def get_etf_shares_aum(symbol: Annotated[str, "6-digit ETF code"]) -> str:
    """Fetch the latest disclosed ETF shares and assets under management."""
    assert_tool_allowed("get_etf_shares_aum")
    return route_to_vendor("get_etf_shares_aum", symbol)


@tool
def get_etf_announcements(
    symbol: Annotated[str, "6-digit ETF code"],
    end_date: Annotated[str, "YYYY-MM-DD analysis date"],
) -> str:
    """Fetch dated fund announcements up to the analysis date."""
    assert_tool_allowed("get_etf_announcements")
    return route_to_vendor("get_etf_announcements", symbol, end_date)


@tool
def get_etf_peer_comparison(
    symbol: Annotated[str, "6-digit ETF code"],
) -> str:
    """Compare same-index listed ETFs on fees, disclosed shares/AUM, and liquidity.

    Does not include premium/discount, tracking error, or holdings exposure.
    """
    assert_tool_allowed("get_etf_peer_comparison")
    return route_to_vendor("get_etf_peer_comparison", symbol)


@tool
def get_etf_structure_alerts(
    symbol: Annotated[str, "6-digit ETF code"],
) -> str:
    """Return rule alerts for disclosed share/AUM spikes and thin turnover."""
    assert_tool_allowed("get_etf_structure_alerts")
    return route_to_vendor("get_etf_structure_alerts", symbol)
