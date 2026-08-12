from unittest.mock import MagicMock

from tradingagents.dataflows.instrument import profile_for_stock
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_stock_v2_rebuilds_product_aware_workflow():
    graph = MagicMock()
    graph.config = {"checkpoint_enabled": False}
    graph.selected_analysts = ("market",)
    graph.workflow = MagicMock()
    rebuilt_workflow = MagicMock()
    graph.graph_setup.setup_graph.return_value = rebuilt_workflow
    graph.propagator.get_graph_args.return_value = {"config": {}}
    graph.propagator.create_initial_state.return_value = {"initialized": True}
    graph.memory_log.get_past_context.return_value = ""
    profile = profile_for_stock("600000", exchange="SSE").to_dict()

    initial_state, _, _ = TradingAgentsGraph.prepare_graph_run(
        graph,
        "600000",
        "2026-05-12",
        analysis_mode="stock",
        analysis_product="a_share_stock",
        instrument_profile=profile,
    )

    graph.graph_setup.setup_graph.assert_called_once_with(
        ("market",),
        analysis_mode="stock",
        analysis_product="a_share_stock",
    )
    rebuilt_workflow.compile.assert_called_once_with()
    assert initial_state == {"initialized": True}
