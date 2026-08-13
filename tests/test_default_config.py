from tradingagents.default_config import DEFAULT_CONFIG


def test_default_llm_provider_is_openrouter():
    assert DEFAULT_CONFIG["llm_provider"] == "openrouter"
    assert DEFAULT_CONFIG["deep_think_llm"] == "deepseek/deepseek-chat"
    assert DEFAULT_CONFIG["quick_think_llm"] == "deepseek/deepseek-chat"
