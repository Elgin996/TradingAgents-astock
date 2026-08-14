import pytest
from tradingagents.dataflows.a_stock import is_etf_ticker, _normalize_ticker
from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.parametrize(
    "symbol,expected_etf,expected_code",
    [
        ("517520.etf", True, "517520"),
        ("159242.ETF", True, "159242"),
        ("510300", True, "510300"),
        ("588000", True, "588000"),
        ("159915", True, "159915"),
        ("560010", True, "560010"),
        ("600519", False, "600519"),
        ("000001", False, "000001"),
        ("300750", False, "300750"),
        ("688017", False, "688017"),
        ("600519.SH", False, "600519"),
    ],
)
def test_etf_detection_and_normalization(symbol, expected_etf, expected_code):
    assert is_etf_ticker(symbol) == expected_etf
    assert _normalize_ticker(symbol) == expected_code


def test_etf_auto_defaults_to_market_analyst(monkeypatch):
    """When analyzing an ETF without explicit analyst selection, default to ['market']."""
    created = []

    class FakeClient:
        def __init__(self, **kw): pass
        def get_llm(self):
            class FakeLLM:
                def invoke(self, *a, **kw): return "OK"
                def bind_tools(self, *a, **kw): return self
            return FakeLLM()

    from tradingagents.graph import trading_graph as tg
    monkeypatch.setattr(tg, "create_llm_client", lambda *a, **kw: FakeClient())

    ta = TradingAgentsGraph(debug=False)
    # Default without ticker
    assert "fundamentals" in ta.selected_analysts

    # Prepare for ETF ticker: should auto-switch to market analyst only
    state, args, step = ta.prepare_graph_run("517520.etf", "2026-08-14")
    assert ta.selected_analysts == ["market"]
