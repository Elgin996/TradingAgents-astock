"""R6 — empty graph stream must raise an actionable error."""

from unittest.mock import MagicMock

import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_run_graph_raises_actionable_error_on_empty_stream(monkeypatch, tmp_path):
    mock_client = MagicMock()
    mock_client.get_llm.return_value = MagicMock()
    monkeypatch.setattr(
        "tradingagents.graph.trading_graph.create_llm_client",
        lambda **kwargs: mock_client,
    )

    cfg = {
        **DEFAULT_CONFIG,
        "data_cache_dir": str(tmp_path / "cache"),
        "results_dir": str(tmp_path / "results"),
        "memory_log_path": str(tmp_path / "memory.md"),
    }
    ta = TradingAgentsGraph(config=cfg, selected_analysts=["market"], debug=True)
    ta.graph = MagicMock()
    ta.graph.stream.return_value = iter([])
    ta.memory_log = MagicMock()
    ta.memory_log.get_past_context.return_value = ""

    with pytest.raises(RuntimeError, match="produced no state"):
        ta.propagate("600519", "2024-01-15")
