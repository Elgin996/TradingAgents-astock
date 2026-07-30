"""Unit tests for model-specific structured-output dispatch."""

import pytest
from pydantic import BaseModel

from tradingagents.llm_clients.capabilities import get_capabilities
from tradingagents.llm_clients.openai_client import MinimaxChatOpenAI


@pytest.mark.unit
def test_deepseek_v4_and_reasoner_reject_tool_choice():
    for model in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-reasoner"):
        capabilities = get_capabilities(model)
        assert capabilities.supports_tool_choice is False
        assert capabilities.requires_reasoning_content_roundtrip is True


@pytest.mark.unit
def test_minimax_m2_variants_support_tool_choice_and_reasoning_split():
    for model in ("MiniMax-M2", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"):
        capabilities = get_capabilities(model)
        assert capabilities.supports_tool_choice is True
        assert capabilities.supports_json_mode is False
        assert capabilities.supports_reasoning_split is True


@pytest.mark.unit
def test_unknown_model_uses_permissive_defaults():
    capabilities = get_capabilities("some-future-model")
    assert capabilities.supports_tool_choice is True
    assert capabilities.preferred_structured_method == "function_calling"
    assert capabilities.supports_reasoning_split is False


@pytest.mark.unit
def test_future_minimax_family_does_not_inherit_m2_reasoning_split():
    capabilities = get_capabilities("MiniMax-M3")
    assert capabilities.supports_tool_choice is True
    assert capabilities.supports_reasoning_split is False


@pytest.mark.unit
def test_minimax_payload_enables_reasoning_split():
    client = MinimaxChatOpenAI(
        model="MiniMax-M2.7",
        api_key="placeholder",
        base_url="https://api.minimax.chat/v1",
    )
    payload = client._get_request_payload([{"role": "user", "content": "hi"}])
    assert payload.get("reasoning_split") is True


@pytest.mark.unit
def test_minimax_payload_does_not_enable_reasoning_split_for_custom_model():
    client = MinimaxChatOpenAI(
        model="custom-minimax-model",
        api_key="placeholder",
        base_url="https://api.minimax.chat/v1",
    )
    payload = client._get_request_payload([{"role": "user", "content": "hi"}])
    assert "reasoning_split" not in payload


@pytest.mark.unit
def test_minimax_structured_output_keeps_schema_and_tool_choice():
    class _Sample(BaseModel):
        answer: str

    client = MinimaxChatOpenAI(
        model="MiniMax-M2.7",
        api_key="placeholder",
        base_url="https://api.minimax.chat/v1",
    )
    wrapped = client.with_structured_output(_Sample)
    first = wrapped.steps[0] if hasattr(wrapped, "steps") else wrapped
    kwargs = getattr(first, "kwargs", {})

    tool_choice = kwargs.get("tool_choice")
    assert tool_choice == {
        "type": "function",
        "function": {"name": "_Sample"},
    }
    assert any(
        tool.get("function", {}).get("name") == "_Sample"
        for tool in kwargs.get("tools", [])
    )


@pytest.mark.unit
def test_deepseek_v3_family_keeps_permissive_defaults():
    """V3.2 是 catalog 里在售型号，其 tool_choice 行为未实测过，
    不能被 V4 的结论覆盖（原 `^deepseek-v\\d` 会误伤）。"""
    for model in ("deepseek-v3", "deepseek-v3.2", "deepseek-chat"):
        capabilities = get_capabilities(model)
        assert capabilities.supports_tool_choice is True
        assert capabilities.preferred_structured_method == "function_calling"


@pytest.mark.unit
def test_deepseek_v4_family_still_matched_by_pattern():
    for model in ("deepseek-v4", "deepseek-v4.1", "deepseek-v4-turbo"):
        assert get_capabilities(model).supports_tool_choice is False


@pytest.mark.unit
def test_explicit_tool_choice_is_dropped_for_unsupported_model():
    """能力表声明「不支持 tool_choice」就必须真正生效。
    原实现用 setdefault，调用方显式传入时会被保留，API 调用照样失败。"""
    from unittest.mock import patch
    from langchain_openai import ChatOpenAI
    from tradingagents.llm_clients.openai_client import DeepSeekChatOpenAI

    client = DeepSeekChatOpenAI(model="deepseek-v4-pro", api_key="x")

    class _Schema(BaseModel):
        value: str

    # 必须 patch 到 ChatOpenAI（再上一层）——patch NormalizedChatOpenAI 会把
    # 待测实现本身替换掉，测试就永远绿。
    with patch.object(ChatOpenAI, "with_structured_output", return_value="ok") as parent:
        client.with_structured_output(_Schema, tool_choice="required")

    assert parent.call_args.kwargs["tool_choice"] is None
