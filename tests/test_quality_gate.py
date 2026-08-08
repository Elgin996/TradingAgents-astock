"""Phase 5.3 quality gate: selected analysts, scaled threshold, block policy."""

from unittest.mock import MagicMock

from langgraph.graph import END

from tradingagents.agents.quality_gate import (
    REPORT_FIELDS,
    _fail_threshold,
    create_quality_gate,
)
from tradingagents.graph.conditional_logic import ConditionalLogic


def _state(reports: dict):
    base = {
        "trade_date": "2026-05-12",
        "company_of_interest": "600519",
        "data_quality_failed": False,
    }
    for field in REPORT_FIELDS.values():
        base[field] = ""
    base.update(reports)
    return base


def test_fail_threshold_scales():
    assert _fail_threshold(7) == 4
    assert _fail_threshold(3) == 2
    assert _fail_threshold(1) == 2


def test_only_selected_analysts_graded():
    llm = MagicMock()
    gate = create_quality_gate(llm, selected_analysts=["market", "news"])
    # Unselected analysts empty would have failed under the old always-grade-7 logic.
    long_ok = ("x" * 250) + "\n| a | b |\n| --- | --- |\n"
    result = gate(
        _state(
            {
                "market_report": long_ok,
                "news_report": long_ok,
            }
        )
    )
    assert result["data_quality_failed"] is False
    assert "技术分析师" in result["data_quality_summary"]
    assert "新闻分析师" in result["data_quality_summary"]
    assert "政策分析师" not in result["data_quality_summary"]


def test_selected_analysts_empty_reports_fail():
    llm = MagicMock()
    gate = create_quality_gate(llm, selected_analysts=["market", "news", "social"])
    result = gate(_state({}))
    assert result["data_quality_failed"] is True


def test_quality_gate_summary_has_no_internal_identifiers():
    llm = MagicMock()
    gate = create_quality_gate(llm, selected_analysts=["market", "news"])
    long_ok = ("x" * 250) + "\n| a | b |\n| --- | --- |\n"
    out = gate(
        _state(
            {
                "market_report": long_ok,
                "news_report": long_ok,
            }
        )
    )["data_quality_summary"]
    assert "data_quality_failed" not in out
    assert "fail_count" not in out
    assert "threshold" not in out
    assert "通过" in out


def test_block_policy_ends_graph():
    logic = ConditionalLogic(quality_gate_policy="block")
    assert logic.should_continue_after_quality_gate({"data_quality_failed": True}) is END
    assert (
        logic.should_continue_after_quality_gate({"data_quality_failed": False})
        == "Bull Researcher"
    )


def test_warn_policy_continues():
    logic = ConditionalLogic(quality_gate_policy="warn")
    assert (
        logic.should_continue_after_quality_gate({"data_quality_failed": True})
        == "Bull Researcher"
    )
