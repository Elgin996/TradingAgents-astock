"""F5.1 — max_recur_limit reaches Propagator.get_graph_args."""

from unittest.mock import MagicMock

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_recursion_limit_is_configurable(monkeypatch, tmp_path):
    mock_client = MagicMock()
    mock_client.get_llm.return_value = MagicMock()
    monkeypatch.setattr(
        "tradingagents.graph.trading_graph.create_llm_client",
        lambda **kwargs: mock_client,
    )

    cfg = {
        **DEFAULT_CONFIG,
        "max_recur_limit": 42,
        "data_cache_dir": str(tmp_path / "cache"),
        "results_dir": str(tmp_path / "results"),
        "memory_log_path": str(tmp_path / "memory.md"),
    }
    ta = TradingAgentsGraph(config=cfg, selected_analysts=["market"])
    assert ta.propagator.get_graph_args()["config"]["recursion_limit"] == 42


def test_default_max_recur_limit_is_250():
    assert DEFAULT_CONFIG["max_recur_limit"] == 250
