"""Tests for OpenRouter reasoning-effort request configuration."""

from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_openrouter_reasoning_effort_uses_chat_completions_extra_body():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {
        "llm_provider": "openrouter",
        "openrouter_reasoning_effort": "high",
    }

    assert graph._get_provider_kwargs() == {
        "extra_body": {"reasoning": {"effort": "high"}}
    }


def test_openrouter_uses_no_reasoning_parameter_by_default():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {"llm_provider": "openrouter"}

    assert graph._get_provider_kwargs() == {}
