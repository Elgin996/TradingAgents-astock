"""LangChain tools exposed only to ETF analysts."""

from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.capability_guard import assert_tool_allowed
from tradingagents.dataflows.interface import route_to_vendor


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
    end_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
) -> str:
    """Fetch fund announcements published by the analysis date."""
    assert_tool_allowed("get_etf_announcements")
    return route_to_vendor("get_etf_announcements", symbol, end_date)
