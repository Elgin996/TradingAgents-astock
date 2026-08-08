from tradingagents.graph.setup import DEFAULT_ANALYSTS, ETF_ANALYSTS, resolve_analysts


def test_etf_mode_has_only_etf_appropriate_analysts():
    assert resolve_analysts("etf") == ETF_ANALYSTS
    assert set(ETF_ANALYSTS) == {
        "market",
        "etf_liquidity",
        "etf_structure",
        "etf_index_news",
    }
    assert not {"fundamentals", "hot_money", "lockup", "social"} & set(ETF_ANALYSTS)


def test_stock_mode_remains_unchanged():
    assert resolve_analysts("stock") == DEFAULT_ANALYSTS
