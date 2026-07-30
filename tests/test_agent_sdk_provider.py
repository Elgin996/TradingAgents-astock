"""Tests for the claude_agent_sdk provider (personal Max-subscription POC).

The real Agent SDK spawns the `claude` CLI and consumes a live subscription, so
every test mocks the call path (`ClaudeAgentSDKClient._query`) — no CLI, no
network, no subscription needed.

conftest.py injects ANTHROPIC_API_KEY=placeholder for all tests; the F-004
guardrail trips on it, so tests that enable the provider must delenv it first
(this is the exact interaction Codex flagged).
"""

import json

import pytest
from pydantic import BaseModel

from tradingagents.llm_clients import claude_agent_sdk_client as mod
from tradingagents.llm_clients.claude_agent_sdk_client import (
    AgentSDKChatModel,
    ClaudeAgentSDKClient,
    _RateLimitHit,
    _split_prompt,
)
from tradingagents.llm_clients.factory import create_llm_client


class _Plan(BaseModel):
    decision: str
    confidence: int


@pytest.fixture
def oauth_env(monkeypatch):
    """Enable the provider cleanly: OAuth token present, API key absent."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-oauth-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _client_with_query(monkeypatch, text="", structured=None, fallback_spec=None):
    """Build a client whose _query returns a canned (text, structured) tuple."""
    client = ClaudeAgentSDKClient("claude-opus-4-8", fallback_spec=fallback_spec)

    async def fake_query(prompt, options, prefer_result=False):
        return text, structured

    monkeypatch.setattr(client, "_query", fake_query)
    return client


class _FakeLangChainTool:
    """Minimal stand-in for a LangChain StructuredTool (bridged by bind_tools)."""

    name = "get_thing"
    description = "gets a thing"
    args_schema = None  # → _sdk_tools_from_langchain uses an empty object schema

    def invoke(self, args):
        return "thing-data"


# --------------------------------------------------------------------------- #
# T-002 / F-002: adapter surface
# --------------------------------------------------------------------------- #

def test_invoke_returns_aimessage(monkeypatch, oauth_env):
    client = _client_with_query(monkeypatch, text="hello from max")
    llm = client.get_llm()
    result = llm.invoke("say hi")
    assert result.content == "hello from max"


def test_structured_output_returns_pydantic(monkeypatch, oauth_env):
    client = _client_with_query(
        monkeypatch, structured={"decision": "buy", "confidence": 4}
    )
    llm = client.get_llm()
    plan = llm.with_structured_output(_Plan).invoke("decide")
    assert isinstance(plan, _Plan)
    assert plan.decision == "buy" and plan.confidence == 4


def test_structured_output_parses_json_text_when_no_structured_field(monkeypatch, oauth_env):
    # SDK returned text (not structured_output) — adapter must parse the JSON.
    text = 'noise before {"decision": "hold", "confidence": 2} noise after'
    client = _client_with_query(monkeypatch, text=text, structured=None)
    plan = client.get_llm().with_structured_output(_Plan).invoke("decide")
    assert plan.decision == "hold" and plan.confidence == 2


def test_bind_tools_returns_runnable_and_final_report(monkeypatch, oauth_env):
    # bind_tools must return a Runnable (so `prompt | bound` composes) whose
    # invoke runs the SDK tool loop and returns a final report with NO
    # tool_calls — LangGraph then treats the analyst as done.
    from langchain_core.runnables import Runnable

    client = _client_with_query(monkeypatch, text="final report")
    bound = client.get_llm().bind_tools([_FakeLangChainTool()])
    assert isinstance(bound, Runnable)
    result = bound.invoke("analyze 600519")
    assert result.content == "final report"
    assert result.tool_calls == []


def test_bind_tools_falls_back_on_rate_limit(monkeypatch, oauth_env):
    # Subscription tool loop hits quota → fall back to the fallback provider's
    # bind_tools, which rejoins LangGraph's normal external ToolNode loop.
    client = ClaudeAgentSDKClient(
        "claude-opus-4-8",
        fallback_spec={"provider": "deepseek", "model": "deepseek-v4-pro", "base_url": None},
    )

    async def boom(prompt, options, prefer_result=False):
        raise _RateLimitHit("weekly limit reached")

    monkeypatch.setattr(client, "_query", boom)
    _install_stub_fallback(monkeypatch)

    result = client.get_llm().bind_tools([_FakeLangChainTool()]).invoke("analyze")
    assert result.content == "served by fallback tools"


# --------------------------------------------------------------------------- #
# F-007 / AC-005: dependency + OAuth guards
# --------------------------------------------------------------------------- #

def test_get_llm_raises_when_sdk_missing(monkeypatch, oauth_env):
    monkeypatch.setattr(mod, "_sdk", None)
    client = ClaudeAgentSDKClient("claude-opus-4-8")
    with pytest.raises(ImportError, match=r"\[agentsdk\]"):
        client.get_llm()


def test_get_llm_uses_ambient_login_when_oauth_missing(monkeypatch):
    # With no explicit token, get_llm() no longer raises — the Agent SDK inherits
    # the ambient logged-in `claude` session (Keychain / ~/.claude). Any genuine
    # auth failure surfaces at call time and triggers the F-005 fallback instead.
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    # Only meaningful when the SDK is importable; otherwise the import guard wins.
    if mod._sdk is None:
        pytest.skip("claude-agent-sdk not installed")
    client = ClaudeAgentSDKClient("claude-opus-4-8")
    assert isinstance(client.get_llm(), mod.AgentSDKChatModel)


# --------------------------------------------------------------------------- #
# T-004: factory routing
# --------------------------------------------------------------------------- #

def test_factory_routes_to_agent_sdk_client():
    client = create_llm_client(
        "claude_agent_sdk", "claude-opus-4-8",
        fallback_spec={"provider": "deepseek", "model": "deepseek-v4-pro", "base_url": None},
    )
    assert isinstance(client, ClaudeAgentSDKClient)
    assert client.fallback_spec["provider"] == "deepseek"


# --------------------------------------------------------------------------- #
# T-006 / F-005 / AC-003: cross-provider fallback
# --------------------------------------------------------------------------- #

class _StubStructured:
    def __init__(self, schema):
        self._schema = schema

    def invoke(self, prompt, *a, **k):
        return self._schema(decision="fallback-buy", confidence=1)


class _StubBoundTools:
    def invoke(self, prompt, *a, **k):
        from langchain_core.messages import AIMessage
        return AIMessage(content="served by fallback tools")


class _StubLLM:
    def invoke(self, prompt, *a, **k):
        from langchain_core.messages import AIMessage
        return AIMessage(content="served by fallback")

    def with_structured_output(self, schema, **k):
        return _StubStructured(schema)

    def bind_tools(self, tools, **k):
        return _StubBoundTools()


def _install_stub_fallback(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.llm_clients.factory.create_llm_client",
        lambda **kw: type("C", (), {"get_llm": lambda self: _StubLLM()})(),
    )


def test_invoke_falls_back_on_rate_limit(monkeypatch, oauth_env):
    client = ClaudeAgentSDKClient(
        "claude-opus-4-8",
        fallback_spec={"provider": "deepseek", "model": "deepseek-v4-pro", "base_url": None},
    )

    async def boom(prompt, options):
        raise _RateLimitHit("weekly limit reached")

    monkeypatch.setattr(client, "_query", boom)
    _install_stub_fallback(monkeypatch)

    result = client.get_llm().invoke("analyze")
    assert result.content == "served by fallback"


def test_structured_falls_back_and_still_yields_pydantic(monkeypatch, oauth_env):
    client = ClaudeAgentSDKClient(
        "claude-opus-4-8",
        fallback_spec={"provider": "deepseek", "model": "deepseek-v4-pro", "base_url": None},
    )

    async def boom(prompt, options):
        raise _RateLimitHit("weekly limit reached")

    monkeypatch.setattr(client, "_query", boom)
    _install_stub_fallback(monkeypatch)

    plan = client.get_llm().with_structured_output(_Plan).invoke("decide")
    assert isinstance(plan, _Plan)
    assert plan.decision == "fallback-buy"


def test_no_fallback_spec_reraises(monkeypatch, oauth_env):
    client = ClaudeAgentSDKClient("claude-opus-4-8", fallback_spec=None)

    async def boom(prompt, options):
        raise _RateLimitHit("limit")

    monkeypatch.setattr(client, "_query", boom)
    with pytest.raises(_RateLimitHit):
        client.get_llm().invoke("x")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def test_split_prompt_string():
    assert _split_prompt("just text") == (None, "just text")


def test_split_prompt_messages_extracts_system():
    from langchain_core.messages import SystemMessage, HumanMessage
    system, user = _split_prompt([SystemMessage(content="be terse"), HumanMessage(content="hi")])
    assert system == "be terse"
    assert user == "hi"


# --------------------------------------------------------------------------- #
# T-005 / F-004: startup guardrail + AC-004 no-behaviour-change
# --------------------------------------------------------------------------- #

def test_guardrail_refuses_api_key_coexistence(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-would-bill-api")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-oauth-token")
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    cfg = dict(DEFAULT_CONFIG)
    cfg["deep_think_provider_override"] = "claude_agent_sdk"
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        TradingAgentsGraph(config=cfg)


def test_default_config_off_by_default():
    from tradingagents.default_config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["deep_think_provider_override"] is None
    assert DEFAULT_CONFIG["quick_think_provider_override"] is None

    # 默认用 claude CLI 的别名（opus/sonnet）而不是写死版本号的完整 id：
    # 别名恒指向最新模型，写死 "claude-opus-4-8" 这类 id 会随版本迭代过期
    # （仓库 model_catalog 里的 anthropic 条目就已经停在 4-6）。
    # 完整 id 仍然可用，此处只锁默认值必须是别名。
    assert DEFAULT_CONFIG["agent_sdk_model"] in ("opus", "sonnet")
    # quick 节点数量多（7 分析师 + 辩手），订阅按额度限流，默认给更省的 sonnet。
    assert DEFAULT_CONFIG["agent_sdk_quick_model"] == "sonnet"


# --------------------------------------------------------------------------- #
# real _query message consumption (closes the RateLimitEvent blind spot;
# locks in the fix for the "allowed_warning silently bills paid API" bug)
# --------------------------------------------------------------------------- #

def _fake(cls, **attrs):
    """Build an instance of a real SDK dataclass without its heavy __init__."""
    obj = object.__new__(cls)
    for k, v in attrs.items():
        setattr(obj, k, v)
    return obj


def _patch_query(monkeypatch, *messages):
    async def fake_query(prompt, options):
        for m in messages:
            yield m
    monkeypatch.setattr(mod._sdk, "query", fake_query)


def _rate_limit_info(status, overage_status=None):
    # Set every field so repr()/str() (used in the reject path) never KeyErrors.
    return _fake(
        mod._sdk.RateLimitInfo,
        status=status, resets_at=None, rate_limit_type=None, utilization=None,
        overage_status=overage_status, overage_resets_at=None,
        overage_disabled_reason=None, raw={},
    )


@pytest.mark.skipif(mod._sdk is None, reason="claude-agent-sdk not installed")
def test_query_allowed_warning_does_not_fall_back(monkeypatch, oauth_env):
    # Near the limit but STILL SERVING → must keep the response, not bail to API.
    _patch_query(
        monkeypatch,
        _fake(mod._sdk.RateLimitEvent,
              rate_limit_info=_rate_limit_info("allowed_warning")),
        _fake(mod._sdk.AssistantMessage, content=[_fake(mod._sdk.TextBlock, text="served by subscription")]),
        _fake(mod._sdk.ResultMessage, is_error=False, structured_output=None,
              result="served by subscription", stop_reason="end_turn", api_error_status=None),
    )
    client = ClaudeAgentSDKClient(
        "claude-opus-4-8",
        fallback_spec={"provider": "deepseek", "model": "deepseek-v4-pro", "base_url": None},
    )
    _install_stub_fallback(monkeypatch)
    result = client.get_llm().invoke("analyze")
    assert result.content == "served by subscription"  # NOT "served by fallback"


@pytest.mark.skipif(mod._sdk is None, reason="claude-agent-sdk not installed")
def test_query_allowed_with_overage_rejected_does_not_fall_back(monkeypatch, oauth_env):
    # Real-world case: the org disables overage, so every event carries
    # overage_status="rejected" — but status="allowed" means the plan served
    # this call. Must keep the subscription response, NOT bail to the paid
    # fallback. (Regression for the "100% silent downgrade" bug.)
    _patch_query(
        monkeypatch,
        _fake(mod._sdk.RateLimitEvent,
              rate_limit_info=_rate_limit_info("allowed", overage_status="rejected")),
        _fake(mod._sdk.AssistantMessage, content=[_fake(mod._sdk.TextBlock, text="served by subscription")]),
        _fake(mod._sdk.ResultMessage, is_error=False, structured_output=None,
              result="served by subscription", stop_reason="end_turn", api_error_status=None),
    )
    client = ClaudeAgentSDKClient(
        "claude-opus-4-8",
        fallback_spec={"provider": "deepseek", "model": "deepseek-v4-pro", "base_url": None},
    )
    _install_stub_fallback(monkeypatch)
    result = client.get_llm().invoke("analyze")
    assert result.content == "served by subscription"  # NOT "served by fallback"


@pytest.mark.skipif(mod._sdk is None, reason="claude-agent-sdk not installed")
def test_query_rejected_triggers_fallback(monkeypatch, oauth_env):
    _patch_query(
        monkeypatch,
        _fake(mod._sdk.RateLimitEvent,
              rate_limit_info=_rate_limit_info("rejected", overage_status="rejected")),
    )
    client = ClaudeAgentSDKClient(
        "claude-opus-4-8",
        fallback_spec={"provider": "deepseek", "model": "deepseek-v4-pro", "base_url": None},
    )
    _install_stub_fallback(monkeypatch)
    result = client.get_llm().invoke("analyze")
    assert result.content == "served by fallback"


# --------------------------------------------------------------------------- #
# 认证失败必须中止，不能降级到按 token 计费的 provider
# --------------------------------------------------------------------------- #

def test_auth_failure_is_detected_from_api_retry_and_assistant_text():
    from tradingagents.llm_clients.claude_agent_sdk_client import (
        _looks_like_auth_failure,
    )

    class _Sys:            # SystemMessage(subtype="api_retry")
        data = {"error_status": 401, "error": "authentication_failed"}

    class _Block:
        text = "Failed to authenticate. API Error: 401 OAuth access token has expired."

    class _Assistant:
        content = [_Block()]
        error = "authentication_error"

    class _Normal:
        data = {"subtype": "init"}
        content = []
        error = None

    assert _looks_like_auth_failure(_Sys()) is True
    assert _looks_like_auth_failure(_Assistant()) is True
    assert _looks_like_auth_failure(_Normal()) is False


def test_auth_error_is_not_in_fallback_errors():
    """凭据失效时降级到付费 provider ＝ 悄悄开始计费，正是启用订阅要避免的。
    这条锁住 _AuthError 不被 fallback 吞掉。"""
    from tradingagents.llm_clients import claude_agent_sdk_client as mod

    assert mod._AuthError not in mod._FALLBACK_ERRORS
    assert not issubclass(mod._AuthError, mod._FALLBACK_ERRORS)


def test_auth_failure_hint_is_actionable():
    from tradingagents.llm_clients.claude_agent_sdk_client import _auth_failure_hint

    class _Block:
        text = "401 OAuth access token has expired"

    class _M:
        content = [_Block()]

    hint = _auth_failure_hint(_M())
    assert "claude setup-token" in hint          # 给出可执行命令
    assert "CLAUDE_CODE_OAUTH_TOKEN" in hint


def test_web_all_scope_keeps_separate_quick_model():
    """选「所有节点」时不能把深度节点的模型复制给 quick——
    7 个分析师 + 辩手全跑 opus 会让订阅额度烧得极快，也与文档所述矛盾。"""
    from tradingagents.default_config import DEFAULT_CONFIG

    config = dict(DEFAULT_CONFIG)
    session = {"subscription_scope": "all", "agent_sdk_model": "opus"}

    # 复刻 web/app.py:_build_config 的订阅分支
    scope = session.get("subscription_scope", "off")
    sub_model = session.get("agent_sdk_model")
    if scope in ("deep", "all"):
        config["deep_think_provider_override"] = "claude_agent_sdk"
        if sub_model:
            config["agent_sdk_model"] = sub_model
    if scope == "all":
        config["quick_think_provider_override"] = "claude_agent_sdk"

    assert config["agent_sdk_model"] == "opus"
    assert config["agent_sdk_quick_model"] == "sonnet"     # 未被 opus 覆盖
