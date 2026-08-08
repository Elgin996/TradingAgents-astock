"""Unit tests for CLI analyze parity fixes (F6.1–F6.3)."""

from unittest.mock import MagicMock, patch

import pytest
import typer

from cli.models import AnalystType
from cli.utils import ANALYST_ORDER as ANALYST_ORDER_DISPLAY


EXPECTED_ANALYSTS = {
    "market",
    "social",
    "news",
    "fundamentals",
    "policy",
    "hot_money",
    "lockup",
}


class TestSevenAnalysts:
    def test_analyst_type_has_all_seven(self):
        values = {member.value for member in AnalystType}
        assert values == EXPECTED_ANALYSTS

    def test_utils_analyst_order_lists_all_seven(self):
        keys = [a.value for _, a in ANALYST_ORDER_DISPLAY]
        assert keys == [
            "market",
            "social",
            "news",
            "fundamentals",
            "policy",
            "hot_money",
            "lockup",
        ]

    def test_main_analyst_order_derived_from_utils(self):
        from cli.main import ANALYST_ORDER

        assert ANALYST_ORDER == [a.value for _, a in ANALYST_ORDER_DISPLAY]
        assert len(ANALYST_ORDER) == 7

    def test_message_buffer_maps_a_share_analysts(self):
        from cli.main import MessageBuffer

        buf = MessageBuffer()
        buf.init_for_analysis(
            ["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"]
        )
        for key in EXPECTED_ANALYSTS:
            assert key in MessageBuffer.ANALYST_MAPPING
            assert MessageBuffer.ANALYST_MAPPING[key] in buf.agent_status
        assert "policy_report" in buf.report_sections
        assert "hot_money_report" in buf.report_sections
        assert "lockup_report" in buf.report_sections


class TestEmptyStreamGuard:
    def test_empty_trace_exits(self):
        from cli.main import ensure_final_state

        with pytest.raises(typer.Exit) as exc:
            ensure_final_state([])
        assert exc.value.exit_code == 1

    def test_missing_decision_exits(self):
        from cli.main import ensure_final_state

        with pytest.raises(typer.Exit) as exc:
            ensure_final_state([{"market_report": "ok"}])
        assert exc.value.exit_code == 1

    def test_valid_trace_returns_final_state(self):
        from cli.main import ensure_final_state

        final = {"final_trade_decision": "Rating: Buy"}
        assert ensure_final_state([{"x": 1}, final]) is final


class TestCheckpointPrepare:
    def test_run_analysis_uses_prepare_and_finalize(self):
        """CLI must call prepare_graph_run / finalize_graph_run (F6.1)."""
        from cli import main as cli_main

        fake_state = {
            "messages": [],
            "final_trade_decision": "Rating: Hold",
            "market_report": "m",
            "investment_debate_state": {},
            "risk_debate_state": {},
            "trader_investment_plan": "",
            "investment_plan": "",
        }

        graph = MagicMock()
        graph.prepare_graph_run.return_value = ({"init": True}, {"config": {}}, 3)
        graph.graph.stream.return_value = iter([fake_state])
        graph.finalize_graph_run.return_value = "Hold"

        selections = {
            "ticker": "600519",
            "analysis_date": "2026-05-12",
            "research_depth": 1,
            "market_lookback_days": 20,
            "shallow_thinker": "m",
            "deep_thinker": "m",
            "backend_url": None,
            "llm_provider": "minimax",
            "google_thinking_level": None,
            "openai_reasoning_effort": None,
            "anthropic_effort": None,
            "output_language": "Chinese",
            "analysts": [AnalystType.MARKET],
        }

        with patch.object(cli_main, "get_user_selections", return_value=selections), \
             patch.object(cli_main, "TradingAgentsGraph", return_value=graph), \
             patch.object(cli_main, "create_layout", return_value=MagicMock()), \
             patch.object(cli_main, "update_display"), \
             patch.object(cli_main, "Live") as live_cls, \
             patch.object(cli_main.typer, "prompt", side_effect=["N", "N"]):
            live_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
            live_cls.return_value.__exit__ = MagicMock(return_value=False)
            cli_main.run_analysis(checkpoint=True)

        graph.prepare_graph_run.assert_called_once()
        graph.finalize_graph_run.assert_called_once()
        graph.close_graph_run.assert_called_once()
        # Must not fall back to the old manual create_initial_state path.
        graph.propagator.create_initial_state.assert_not_called()
