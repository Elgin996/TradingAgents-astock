"""ETF mode must fail before stock-tool vendor routing."""

import pytest

from tradingagents.agents.utils.fundamental_data_tools import get_fundamentals
from tradingagents.agents.utils.news_data_tools import get_insider_transactions
from tradingagents.agents.utils.signal_data_tools import (
    get_dragon_tiger_board,
    get_industry_comparison,
    get_lockup_expiry,
    get_profit_forecast,
)
from tradingagents.dataflows.capability_guard import (
    CapabilityError,
    reset_active_capabilities,
    set_active_capabilities,
)


@pytest.fixture
def etf_capability_context():
    token = set_active_capabilities(
        {"price_history", "technical_indicators", "index_news_policy"}
    )
    try:
        yield
    finally:
        reset_active_capabilities(token)


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (get_fundamentals, ("510300", "2026-08-07")),
        (get_insider_transactions, ("510300",)),
        (get_profit_forecast, ("510300",)),
        (get_dragon_tiger_board, ("510300", "2026-08-07")),
        (get_lockup_expiry, ("510300", "2026-08-07")),
        (get_industry_comparison, ("510300", "2026-08-07")),
    ],
)
def test_stock_only_tools_raise_before_vendor_routing(etf_capability_context, tool, args):
    """Calling the LangChain tool's underlying function cannot reach a vendor."""
    with pytest.raises(CapabilityError):
        tool.func(*args)
