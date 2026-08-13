# TradingAgents/graph/trading_graph.py

import logging
import os
from pathlib import Path
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, List, Optional

logger = logging.getLogger(__name__)

from langgraph.prebuilt import ToolNode

from tradingagents.llm_clients import create_llm_client

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.vendors.base import VendorError

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_index_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_insider_transactions,
    get_global_news,
    get_profit_forecast,
    get_hot_stocks,
    get_northbound_flow,
    get_concept_blocks,
    get_fund_flow,
    get_dragon_tiger_board,
    get_lockup_expiry,
    get_industry_comparison,
    get_etf_profile,
    get_etf_quote,
    get_etf_shares_aum,
    get_etf_announcements,
    get_etf_peer_comparison,
    get_etf_structure_alerts,
)

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .setup import DEFAULT_ANALYSTS, ROLE_KEYS, GraphSetup, resolve_analysts
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor

# 七个分析师角色——它们受 `selected_analysts` 控制，没选中就不会进图。
_ANALYST_ROLES = frozenset({
    "market", "social", "news", "fundamentals", "policy", "hot_money", "lockup",
})

# 各家 provider 私有的参数：换了 provider 就不能带过去（别家可能直接拒收）。
_PROVIDER_SPECIFIC_KWARGS = frozenset({
    "reasoning_effort",   # openai
    "thinking_level",     # google
    "effort",             # anthropic
})


def _handle_vendor_error(exc: VendorError) -> str:
    """Turn an exhausted external-data route into explicit missing evidence.

    Analyst prompts already require missing data to be disclosed.  Returning a
    ToolMessage here lets the analyst finish with that disclosure, while the
    narrow ``VendorError`` annotation ensures code bugs still abort the run.
    """
    return (
        "DATA_UNAVAILABLE: external data vendors could not satisfy this tool "
        f"request ({exc}). Treat this source as missing, disclose the limitation "
        "in the report, do not invent values, and continue with other evidence."
    )


def _vendor_resilient_tool_node(tools) -> ToolNode:
    """Build a ToolNode that degrades typed vendor outages, and only those."""
    return ToolNode(tools, handle_tool_errors=_handle_vendor_error)


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts: Optional[List[str]] = None,
        debug=False,
        config: Dict[str, Any] = None,
        callbacks: Optional[List] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        selected_analysts = list(selected_analysts or DEFAULT_ANALYSTS)
        self.selected_analysts = tuple(selected_analysts)
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        # Optional: route nodes through a personal Claude Pro/Max subscription
        # via the Claude Agent SDK. `deep_think_provider_override` covers the
        # deep nodes (Research / Portfolio Manager); `quick_think_provider_override`
        # covers the quick nodes (7 tool-using analysts + Bull/Bear / trader /
        # risk debaters). Both on ⇒ every node runs on the subscription. Off by
        # default — behaviour is unchanged when both are None.
        deep_on = self.config.get("deep_think_provider_override") == "claude_agent_sdk"
        quick_on = self.config.get("quick_think_provider_override") == "claude_agent_sdk"

        # F-004 guardrail: ANTHROPIC_API_KEY outranks the subscription OAuth token
        # and would silently bill the pay-per-token API instead of the subscription.
        # Refuse to start rather than surprise-bill the user.
        if (deep_on or quick_on) and os.getenv("ANTHROPIC_API_KEY"):
            # 该 key 优先级高于订阅凭据，泄进 Agent SDK 子进程就会悄悄走按 token
            # 计费的 API。客户端已在子进程环境里把它显式置空，所以这里**不再一律
            # 中止**——否则把 anthropic 用作降级 provider 就成了死结：留着 key 启动
            # 被拦，删掉 key 又会在撞额度真要降级时认证失败。
            logger.warning(
                "ANTHROPIC_API_KEY is set while the claude_agent_sdk override is on. "
                "It is stripped from the Agent SDK subprocess so subscription quota is "
                "used, and kept in this process only so an `anthropic` fallback can "
                "still authenticate. If you did not intend to keep a paid Anthropic "
                "fallback, unset it."
            )

        # 降级配置必须成对给：只改 provider 不改 model，会把主 provider 的模型名
        # 配到另一家去（如 AnthropicClient(model="deepseek-chat")），而这条路径
        # **恰好在撞额度、最需要它工作的时候才被走到**——那时再炸就太晚了。
        # 启动时就校验，而不是留到运行中。
        _fb_provider = self.config.get("agent_sdk_fallback_provider")
        _fb_model = self.config.get("agent_sdk_fallback_model")
        if (deep_on or quick_on) and bool(_fb_provider) != bool(_fb_model):
            missing = "agent_sdk_fallback_model" if _fb_provider else "agent_sdk_fallback_provider"
            given = "agent_sdk_fallback_provider" if _fb_provider else "agent_sdk_fallback_model"
            raise ValueError(
                f"{given} is set but {missing} is not — the two must be configured "
                f"together. Otherwise the fallback pairs one provider with another "
                f"provider's model name and fails exactly when the subscription hits "
                f"its quota. Set both, or leave both unset to fall back to "
                f"llm_provider + its own model."
            )

        def _make_client(override_on, sdk_model_key, fallback_model_key):
            """Build a subscription-backed client when overridden, else the normal
            llm_provider client. Fallback rejoins the paid provider on quota/failure."""
            if override_on:
                # backend_url 是为 llm_provider 配的端点。显式指定了**另一家**
                # provider 做降级时不能把它带过去（例如把 anthropic 降级请求发到
                # MiniMax 网关），否则同样是撞额度那一刻才炸。None ⇒ 该 provider
                # 用自己的默认端点。
                cross_provider = bool(_fb_provider) and _fb_provider != self.config["llm_provider"]
                _fb_provider_resolved = _fb_provider or self.config["llm_provider"]
                fallback_spec = {
                    "provider": _fb_provider_resolved,
                    "model": _fb_model or self.config[fallback_model_key],
                    "base_url": None if cross_provider else self.config.get("backend_url"),
                    # Merge tuning kwargs for the *fallback* provider (not primary).
                    **self._get_provider_kwargs(_fb_provider_resolved),
                    # 带上 callbacks：降级意味着**开始计费**，此时统计/成本回调
                    # 反而看不到这些调用的话，恰好在花钱的时候统计是瞎的。
                    **({"callbacks": self.callbacks} if self.callbacks else {}),
                    # 用户显式配的输出上限也要带过去。否则撞额度降级之后，降级
                    # provider 用它自己的默认上限，报告照样被截断——而这正是
                    # 用户配 max_tokens 想避免的事（#91）。
                    **({"max_tokens": self.config["max_tokens"]}
                       if self.config.get("max_tokens") else {}),
                }
                return create_llm_client(
                    provider="claude_agent_sdk",
                    model=self.config[sdk_model_key],
                    base_url=self.config.get("backend_url"),
                    fallback_spec=fallback_spec,
                )
            return create_llm_client(
                provider=self.config["llm_provider"],
                model=self.config[fallback_model_key],
                base_url=self.config.get("backend_url"),
                **llm_kwargs,
            )

        deep_client = _make_client(deep_on, "agent_sdk_model", "deep_think_llm")
        quick_client = _make_client(quick_on, "agent_sdk_quick_model", "quick_think_llm")

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()

        # 可选：给单个角色指定模型（#39）。不配 = 完全维持 quick/deep 两档的原行为。
        self.role_llms = self._build_role_llms(
            llm_kwargs, deep_on or quick_on, selected_analysts
        )

        self.memory_log = TradingMemoryLog(self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
            quality_gate_policy=self.config.get("quality_gate_policy", "warn"),
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
            resolve_llm=self.role_llms.get,
        )

        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 250)
        )
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.analysis_mode = "stock"
        self.analysis_product = None
        self.instrument_profile = None
        self.analysis_capabilities: list[str] = []
        self.analysis_unavailable_capabilities: dict[str, str] = {}
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(selected_analysts)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _build_role_llms(
        self,
        llm_kwargs: Dict[str, Any],
        subscription_on: bool,
        selected_analysts=None,
    ) -> Dict[str, Any]:
        """按 `config["role_llms"]` 给单个角色单独建 LLM（#39）。

        默认是空表 —— 不配任何角色时行为与以前完全一致（全部走 quick/deep 两档）。
        配了才有意义：让多空辩手用不同厂商的模型，避免同源模型互相不反驳。

        相同 (provider, model, endpoint) 的角色复用同一个实例，不会因为写了 7 个
        角色就建 7 条连接。
        """
        specs = self.config.get("role_llms") or {}
        if not specs:
            return {}

        unknown = sorted(set(specs) - set(ROLE_KEYS))
        if unknown:
            raise ValueError(
                f"role_llms 里有无法识别的角色名：{unknown}。"
                f"合法角色：{', '.join(ROLE_KEYS)}。"
                f"（写错的角色名如果被静默忽略，你会以为配置生效了，实际没有。）"
            )

        # 没被选中的分析师不会进图，就别为它建模型：那会让一个**永远不执行**的节点
        # 因为缺 API key 或缺可选依赖，把一次本来完全正常的分析在启动时就打断。
        if selected_analysts is not None:
            active = set(selected_analysts)
            skipped = [r for r in specs if r in _ANALYST_ROLES and r not in active]
            if skipped:
                specs = {k: v for k, v in specs.items() if k not in skipped}
                logger.info(
                    "role_llms: 跳过未选中的分析师角色 %s（不建模型）",
                    ", ".join(sorted(skipped)),
                )
            if not specs:
                return {}

        if subscription_on:
            # 订阅覆盖是为了不产生 API 账单，这里显式点名哪些角色会绕开它去计费，
            # 不能让人以为"全部走订阅"却在某几个角色上悄悄花钱。
            logger.warning(
                "role_llms 为以下角色单独指定了模型，它们会绕开 claude_agent_sdk "
                "订阅覆盖、按 token 计费：%s", ", ".join(sorted(specs)),
            )

        main_provider = self.config["llm_provider"]
        cache: Dict[tuple, Any] = {}
        resolved: Dict[str, Any] = {}
        for role, spec in specs.items():
            if not isinstance(spec, dict) or not spec.get("model"):
                raise ValueError(
                    f"role_llms['{role}'] 必须是带 model 的字典，"
                    f'例如 {{"provider": "deepseek", "model": "deepseek-chat"}}。'
                )
            provider = spec.get("provider") or main_provider
            # backend_url 是给主 provider 配的端点。换了厂商还把它带过去，请求就会
            # 发到另一家的网关（和 agent_sdk 降级那里同一个坑）。None = 用该
            # provider 自己的默认端点。
            if "backend_url" in spec:
                base_url = spec["backend_url"]
            elif provider.lower() == str(main_provider).lower():
                base_url = self.config.get("backend_url")
            else:
                base_url = None

            # 主 provider 的**专属**参数不能带给另一家：openai 的
            # `reasoning_effort`、google 的 `thinking_level`、anthropic 的 `effort`
            # 都是各家私有的，塞进 qwen / glm / 自建网关的请求体里可能直接被拒。
            # 通用参数（max_tokens / callbacks 等）保留。
            role_kwargs = (
                llm_kwargs if provider.lower() == str(main_provider).lower()
                else {k: v for k, v in llm_kwargs.items()
                      if k not in _PROVIDER_SPECIFIC_KWARGS}
            )

            key = (provider.lower(), spec["model"], base_url)
            if key not in cache:
                cache[key] = create_llm_client(
                    provider=provider,
                    model=spec["model"],
                    base_url=base_url,
                    **role_kwargs,
                ).get_llm()
            resolved[role] = cache[key]

        logger.info(
            "role_llms: %d 个角色单独配置，实际建了 %d 个模型实例",
            len(resolved), len(cache),
        )
        return resolved

    def _get_provider_kwargs(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation.

        When ``provider`` is given (e.g. the Agent SDK fallback), kwargs are
        resolved for that provider rather than the primary ``llm_provider``.
        """
        kwargs = {}
        provider = (provider or self.config.get("llm_provider", "")).lower()

        timeout = self.config.get("llm_timeout")
        if timeout is not None:
            kwargs["timeout"] = timeout

        max_retries = self.config.get("llm_max_retries")
        if max_retries is not None:
            kwargs["max_retries"] = int(max_retries)

        # 与 provider 无关：单次回复的输出上限。撞上它就是报告写一半被截断（#91）。
        max_tokens = self.config.get("max_tokens")
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "openrouter":
            reasoning_effort = self.config.get("openrouter_reasoning_effort")
            if reasoning_effort:
                kwargs["extra_body"] = {"reasoning": {"effort": reasoning_effort}}

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        return kwargs

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": _vendor_resilient_tool_node(
                [
                    # Core stock / index data tools
                    get_stock_data,
                    get_index_data,
                    # Technical indicators
                    get_indicators,
                ]
            ),
            "social": _vendor_resilient_tool_node(
                [
                    # 情绪分析不只读新闻：资金流是最硬的情绪证据，量价给强度，
                    # 强势股榜给热度归因，新闻负责解释成因（#61）。
                    get_news,
                    get_fund_flow,
                    get_hot_stocks,
                    get_stock_data,
                ]
            ),
            "news": _vendor_resilient_tool_node(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                ]
            ),
            "fundamentals": _vendor_resilient_tool_node(
                [
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                    get_profit_forecast,
                    get_industry_comparison,
                ]
            ),
            "policy": _vendor_resilient_tool_node(
                [
                    get_news,
                    get_global_news,
                ]
            ),
            "hot_money": _vendor_resilient_tool_node(
                [
                    get_stock_data,
                    get_news,
                    get_insider_transactions,
                    get_hot_stocks,
                    get_northbound_flow,
                    get_concept_blocks,
                    get_fund_flow,
                    get_dragon_tiger_board,
                    get_industry_comparison,
                ]
            ),
            "lockup": _vendor_resilient_tool_node(
                [
                    get_insider_transactions,
                    get_news,
                    get_fundamentals,
                    get_lockup_expiry,
                ]
            ),
            "etf_liquidity": _vendor_resilient_tool_node(
                [get_stock_data, get_etf_quote]
            ),
            "etf_structure": _vendor_resilient_tool_node(
                [get_etf_profile, get_etf_shares_aum]
            ),
            "etf_index_news": _vendor_resilient_tool_node(
                [get_news, get_global_news, get_etf_announcements]
            ),
            "etf_compare": _vendor_resilient_tool_node(
                [get_etf_peer_comparison, get_etf_structure_alerts]
            ),
        }

    @staticmethod
    def _t1_holding_return(ohlcv, trade_date: str, holding_days: int):
        """Compute return with T+1 open entry and close exit ``holding_days`` later.

        Returns ``(return, actual_days)`` or ``(None, None)`` when bars are insufficient.
        """
        import pandas as pd

        if ohlcv is None or getattr(ohlcv, "empty", True):
            return None, None
        df = ohlcv.sort_values("Date").reset_index(drop=True)
        trade_dt = pd.to_datetime(trade_date)
        future = df[df["Date"] > trade_dt].reset_index(drop=True)
        # Need entry bar + holding_days further bars for exit close.
        if len(future) < holding_days + 1:
            return None, None
        entry = float(future.loc[0, "Open"])
        if entry == 0:
            return None, None
        exit_px = float(future.loc[holding_days, "Close"])
        return (exit_px - entry) / entry, holding_days

    def _load_tracking_index_ohlcv(self, index_code: str, end_str: str):
        """Load index OHLCV for ETF alpha; never silently substitute CSI 300.

        Tracking-index codes are not ordinary equity tickers: Shanghai indexes
        often use ``000xxx`` while Shenzhen theme indexes use ``399xxx``. Stock
        routing would mis-send ``000300`` to Shenzhen, so this path uses
        index-aware Sina symbols and tries the alternate board before giving up.
        """
        import pandas as pd
        from tradingagents.dataflows.a_stock import (
            _normalize_ohlcv_dates,
            _requests,
            _json,
            _index_symbol,
        )
        from tradingagents.dataflows.index_catalog import INDEX_EXCHANGE_BY_CODE

        code = str(index_code).strip()
        if not code:
            return pd.DataFrame()

        preferred = _index_symbol(code)[:2]
        alternate = "sz" if preferred == "sh" else "sh"
        prefixes = (preferred, alternate)

        url = (
            "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "CN_MarketData.getKLineData"
        )
        for prefix in prefixes:
            try:
                params = {
                    "symbol": f"{prefix}{code}",
                    "scale": "240",
                    "ma": "no",
                    "datalen": "800",
                }
                r = _requests.get(url, params=params, timeout=15)
                r.raise_for_status()
                data = _json.loads(r.text)
                if not data:
                    continue
                rows = [
                    {
                        "Date": item["day"],
                        "Open": float(item["open"]),
                        "High": float(item["high"]),
                        "Low": float(item["low"]),
                        "Close": float(item["close"]),
                        "Volume": int(item["volume"]),
                    }
                    for item in data
                ]
                df = _normalize_ohlcv_dates(pd.DataFrame(rows))
                cutoff = pd.to_datetime(end_str)
                return df[df["Date"] <= cutoff]
            except Exception as exc:
                logger.debug(
                    "Index OHLCV %s%s failed: %s", prefix, code, exc
                )
        return pd.DataFrame()

    def _load_csi300_ohlcv(self, end_str: str):
        """Load CSI 300 OHLCV via mootdx (999300) or Sina sh000300."""
        from tradingagents.dataflows.a_stock import _load_ohlcv_astock

        try:
            return _load_ohlcv_astock("999300", end_str)
        except Exception as e:
            logger.debug("mootdx CSI300 (999300) failed: %s; trying Sina sh000300", e)
        return self._load_tracking_index_ohlcv("000300", end_str)

    def _fetch_returns(
        self,
        ticker: str,
        trade_date: str,
        holding_days: int = 5,
        benchmark_code: str | None = None,
    ) -> Tuple[Optional[float], Optional[float], Optional[int]]:
        """Fetch raw and alpha return for ticker over holding_days from trade_date.

        Uses the A-share OHLCV loader (mootdx/Sina), not yfinance. Entry is the
        next session's open after ``trade_date`` (executable T+1), exit is that
        session's close ``holding_days`` trading days later. ETF entries use their
        frozen tracking index when available; legacy/stock entries use CSI 300.

        Returns (raw_return, alpha_return, actual_holding_days) or
        (None, None, None) if price data is unavailable (too recent, delisted,
        or network error).
        """
        try:
            from tradingagents.dataflows.a_stock import _load_ohlcv_astock

            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 21)
            end_str = end.strftime("%Y-%m-%d")

            stock = _load_ohlcv_astock(str(ticker), end_str)
            if benchmark_code:
                benchmark = self._load_tracking_index_ohlcv(
                    str(benchmark_code), end_str
                )
                if benchmark is None or getattr(benchmark, "empty", True):
                    logger.warning(
                        "Tracking-index OHLCV unavailable for %s; skipping alpha",
                        benchmark_code,
                    )
                    raw, days = self._t1_holding_return(stock, trade_date, holding_days)
                    return (raw, None, days) if raw is not None else (None, None, None)
            else:
                benchmark = self._load_csi300_ohlcv(end_str)

            raw, days = self._t1_holding_return(stock, trade_date, holding_days)
            bench_ret, bench_days = self._t1_holding_return(
                benchmark, trade_date, holding_days
            )
            if raw is None or bench_ret is None:
                return None, None, None

            actual_days = min(days, bench_days)
            alpha = float(raw) - float(bench_ret)
            return float(raw), alpha, actual_days
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s (will retry next run): %s",
                ticker, trade_date, e,
            )
            return None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        """Resolve pending log entries for ticker at the start of a new run.

        Fetches returns for each same-ticker pending entry, generates reflections,
        then writes all updates in a single atomic batch write to avoid redundant I/O.
        Skips entries whose price data is not yet available (too recent or delisted).

        Trade-off: only same-ticker entries are resolved per run.  Entries for
        other tickers accumulate until that ticker is run again.
        """
        pending = [e for e in self.memory_log.get_pending_entries() if e["ticker"] == ticker]
        if not pending:
            return

        updates = []
        for entry in pending:
            benchmark_code = (
                entry.get("tracking_index_code")
                if entry.get("analysis_mode") == "etf"
                else None
            )
            raw, alpha, days = self._fetch_returns(
                ticker, entry["date"], benchmark_code=benchmark_code
            )
            if raw is None:
                continue  # price not available yet — try again next run
            reflection = self.reflector.reflect_on_final_decision(
                final_decision=entry.get("decision", ""),
                raw_return=raw,
                alpha_return=alpha,
                benchmark_label=(
                    entry.get("tracking_index_name")
                    or benchmark_code
                    or "CSI 300 (沪深300)"
                ),
            )
            updates.append({
                "ticker": ticker,
                "trade_date": entry["date"],
                "raw_return": raw,
                "alpha_return": alpha,
                "holding_days": days,
                "reflection": reflection,
            })

        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    def propagate(
        self,
        company_name,
        trade_date,
        *,
        analysis_mode: str = "stock",
        analysis_product: Optional[str] = None,
        instrument_profile: Optional[Dict[str, Any]] = None,
    ):
        """Run the trading agents graph for a company on a specific date.

        When ``checkpoint_enabled`` is set in config, the graph is recompiled
        with a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node on a subsequent invocation with the same ticker+date.
        """
        return self._run_graph(
            company_name,
            trade_date,
            analysis_mode=analysis_mode,
            analysis_product=analysis_product,
            instrument_profile=instrument_profile,
        )

    def prepare_graph_run(
        self,
        company_name,
        trade_date,
        callbacks: Optional[List] = None,
        analysis_mode: str = "stock",
        analysis_product: Optional[str] = None,
        instrument_profile: Optional[Dict[str, Any]] = None,
        unavailable_capabilities: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], Optional[int]]:
        """Prepare graph input/args for a fresh or resumed run.

        Returns ``(initial_state, args, checkpoint_step)``. When a checkpoint
        already exists, ``initial_state`` is ``None`` so LangGraph resumes the
        existing thread instead of replaying completed nodes.
        """
        if analysis_product is None and isinstance(instrument_profile, dict):
            candidate = instrument_profile.get("analysis_product")
            if candidate in {
                "a_share_stock",
                "passive_equity_etf",
                "active_equity_etf",
            }:
                analysis_product = candidate
        if analysis_product in {"passive_equity_etf", "active_equity_etf"}:
            analysis_mode = "etf"
        self.ticker = company_name
        self.analysis_mode = analysis_mode
        self.analysis_product = analysis_product
        self.instrument_profile = instrument_profile
        from tradingagents.dataflows.analysis_capabilities import AnalysisCapabilities

        if analysis_mode == "etf" and unavailable_capabilities is None:
            from tradingagents.dataflows.etf_data import probe_etf_capabilities

            unavailable_capabilities = probe_etf_capabilities(
                company_name, str(trade_date)
            )
        capability_model = AnalysisCapabilities.for_instrument(
            instrument_profile,
            analysis_mode,
            unavailable_capabilities,
            analysis_product=analysis_product,
        )
        self.analysis_capabilities = capability_model.to_list()
        self.analysis_unavailable_capabilities = capability_model.unavailable
        # Product-aware validators are bound when the workflow is built.
        # Rebuild every v2 product so a stock product bundle cannot reach the
        # legacy TechnicalEvidenceBundle validator.
        if analysis_mode == "etf" or analysis_product is not None:
            selected = (
                resolve_analysts(analysis_mode, self.analysis_capabilities)
                if analysis_mode == "etf"
                else self.selected_analysts
            )
            if not selected:
                raise RuntimeError(
                    "产品运行时能力探测后没有可执行的分析师；"
                    "请检查行情/基金资料数据源后重试。"
                )
            self.workflow = self.graph_setup.setup_graph(
                selected,
                analysis_mode=analysis_mode,
                analysis_product=analysis_product,
            )
            self.graph = self.workflow.compile()

        # Resolve any pending memory-log entries for this ticker before the pipeline runs.
        self._resolve_pending_entries(company_name)

        checkpoint_enabled = self.config.get("checkpoint_enabled")
        resume_step = None
        report_schema_version = (
            f"{analysis_product}-v2"
            if analysis_product
            else ("etf-v1.3" if analysis_mode == "etf" else "stock-v1")
        )

        # Recompile with a checkpointer if the user opted in.
        if checkpoint_enabled:
            self._checkpointer_ctx = get_checkpointer(
                self.config["data_cache_dir"], company_name
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            resume_step = checkpoint_step(
                self.config["data_cache_dir"],
                company_name,
                str(trade_date),
                analysis_mode,
                report_schema_version,
            )
            if resume_step is not None:
                logger.info(
                    "Resuming from step %d for %s on %s",
                    resume_step,
                    company_name,
                    trade_date,
                )
            else:
                logger.info("Starting fresh for %s on %s", company_name, trade_date)

        args = self.propagator.get_graph_args(callbacks=callbacks)

        # Inject thread_id so same ticker+date resumes, different date starts fresh.
        if checkpoint_enabled:
            tid = thread_id(
                company_name,
                str(trade_date),
                analysis_mode,
                report_schema_version,
            )
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid

        if checkpoint_enabled and resume_step is not None:
            return None, args, resume_step

        # Initialize state only for fresh runs. Passing a new initial state to
        # LangGraph would start a new run and replay completed nodes.
        profile = instrument_profile if isinstance(instrument_profile, dict) else {}
        tracking_index_code = profile.get("tracking_index_code")
        if isinstance(tracking_index_code, dict):
            tracking_index_code = tracking_index_code.get("value", {}).get("code")
        past_context = self.memory_log.get_past_context(
            company_name,
            before_date=str(trade_date),
            analysis_mode=analysis_mode,
            tracking_index_code=tracking_index_code,
        )
        init_agent_state = self.propagator.create_initial_state(
            company_name,
            trade_date,
            past_context=past_context,
            analysis_mode=analysis_mode,
            analysis_product=analysis_product,
            instrument_profile=instrument_profile,
            analysis_capabilities=self.analysis_capabilities,
            analysis_unavailable_capabilities=self.analysis_unavailable_capabilities,
        )
        return init_agent_state, args, resume_step

    def finalize_graph_run(self, company_name, trade_date, final_state):
        """Persist a completed run and clear its checkpoint."""
        if not final_state:
            raise RuntimeError(
                f"Graph produced no state for {company_name} on {trade_date}. "
                "This usually means the quality gate blocked the run, the "
                "recursion limit was hit immediately, or the first node's "
                "provider call failed. Check the log above for the cause."
            )
        decision = final_state.get("final_trade_decision")
        if not decision:
            raise RuntimeError(
                f"Graph completed without a final decision for {company_name} "
                f"on {trade_date}. The pipeline may have halted early "
                "(quality gate, recursion limit, or provider failure)."
            )

        self.curr_state = final_state

        # Log state to disk.
        self._log_state(trade_date, final_state)

        # Store decision for deferred reflection on the next same-ticker run.
        profile = self.instrument_profile if isinstance(self.instrument_profile, dict) else {}
        tracking_index_code = profile.get("tracking_index_code")
        if isinstance(tracking_index_code, dict):
            tracking_index_code = tracking_index_code.get("value", {}).get("code")
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=decision,
            analysis_mode=(
                self.analysis_mode if isinstance(self.analysis_mode, str) else "stock"
            ),
            tracking_index_code=tracking_index_code,
            tracking_index_name=profile.get("tracking_index_name"),
        )

        # Clear checkpoint on successful completion to avoid stale state.
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"],
                company_name,
                str(trade_date),
                self.analysis_mode,
                final_state.get("report_schema_version"),
            )

        return self.process_signal(decision)

    def close_graph_run(self) -> None:
        """Close the active checkpointer context, if any."""
        if self._checkpointer_ctx is not None:
            self._checkpointer_ctx.__exit__(None, None, None)
            self._checkpointer_ctx = None
            self.graph = self.workflow.compile()

    def _run_graph(
        self,
        company_name,
        trade_date,
        *,
        analysis_mode: str = "stock",
        analysis_product: Optional[str] = None,
        instrument_profile: Optional[Dict[str, Any]] = None,
    ):
        """Execute the graph and write the resulting state to disk and memory log."""
        from tradingagents.dataflows.capability_guard import (
            reset_active_analysis_date,
            reset_active_capabilities,
            set_active_analysis_date,
            set_active_capabilities,
        )

        effective_analysis_mode = (
            "etf"
            if analysis_product in {"passive_equity_etf", "active_equity_etf"}
            else analysis_mode
        )

        init_agent_state, args, _ = self.prepare_graph_run(
            company_name,
            trade_date,
            analysis_mode=effective_analysis_mode,
            analysis_product=analysis_product,
            instrument_profile=instrument_profile,
        )
        token = set_active_capabilities(
            self.analysis_capabilities if effective_analysis_mode == "etf" else None
        )
        date_token = set_active_analysis_date(str(trade_date))

        try:
            if self.debug:
                trace = []
                for chunk in self.graph.stream(init_agent_state, **args):
                    if len(chunk["messages"]) == 0:
                        pass
                    else:
                        chunk["messages"][-1].pretty_print()
                        trace.append(chunk)
                if not trace:
                    raise RuntimeError(
                        f"Graph produced no state for {company_name} on {trade_date}. "
                        "This usually means the quality gate blocked the run, the "
                        "recursion limit was hit immediately, or the first node's "
                        "provider call failed. Check the log above for the cause."
                    )
                final_state = trace[-1]
            else:
                final_state = self.graph.invoke(init_agent_state, **args)

            signal = self.finalize_graph_run(company_name, trade_date, final_state)
            return final_state, signal
        finally:
            self.close_graph_run()
            reset_active_analysis_date(date_token)
            reset_active_capabilities(token)

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        invest = final_state.get("investment_debate_state") or {}
        risk = final_state.get("risk_debate_state") or {}
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state.get("company_of_interest", ""),
            "trade_date": final_state.get("trade_date", str(trade_date)),
            "analysis_mode": final_state.get("analysis_mode", self.analysis_mode),
            "analysis_product": final_state.get(
                "analysis_product", self.analysis_product
            ),
            "analysis_capabilities": final_state.get(
                "analysis_capabilities", self.analysis_capabilities
            ),
            "analysis_unavailable_capabilities": final_state.get(
                "analysis_unavailable_capabilities",
                self.analysis_unavailable_capabilities,
            ),
            "report_schema_version": final_state.get(
                "report_schema_version",
                (
                    f"{self.analysis_product}-v2"
                    if self.analysis_product
                    else "etf-v1.3" if self.analysis_mode == "etf" else "stock-v1"
                ),
            ),
            "data_quality_summary": final_state.get("data_quality_summary", ""),
            "data_quality_failed": bool(
                final_state.get("data_quality_failed", False)
            ),
            "market_data_quality": final_state.get("market_data_quality", {}),
            "market_data_decision": final_state.get("market_data_decision", ""),
            "market_snapshot_id": final_state.get("market_snapshot_id", ""),
            "technical_assessment": final_state.get("technical_assessment", {}),
            "technical_evidence_bundle": final_state.get("technical_evidence_bundle", {}),
            "analysis_market_data_bundle": final_state.get(
                "analysis_market_data_bundle", {}
            ),
            "product_technical_evidence_bundle": final_state.get(
                "product_technical_evidence_bundle", {}
            ),
            "technical_shadow_comparison": final_state.get(
                "technical_shadow_comparison"
            ),
            "instrument_profile": final_state.get(
                "instrument_profile", self.instrument_profile
            ),
            "market_report": final_state.get("market_report", ""),
            "sentiment_report": final_state.get("sentiment_report", ""),
            "news_report": final_state.get("news_report", ""),
            "fundamentals_report": final_state.get("fundamentals_report", ""),
            "policy_report": final_state.get("policy_report", ""),
            "hot_money_report": final_state.get("hot_money_report", ""),
            "lockup_report": final_state.get("lockup_report", ""),
            "etf_liquidity_report": final_state.get("etf_liquidity_report", ""),
            "etf_profile_report": final_state.get("etf_profile_report", ""),
            "etf_index_news_report": final_state.get("etf_index_news_report", ""),
            "etf_compare_report": final_state.get("etf_compare_report", ""),
            "investment_debate_state": {
                "bull_history": invest.get("bull_history", ""),
                "bear_history": invest.get("bear_history", ""),
                "history": invest.get("history", ""),
                "current_response": invest.get("current_response", ""),
                "judge_decision": invest.get("judge_decision", ""),
            },
            "trader_investment_decision": final_state.get("trader_investment_plan", ""),
            "risk_debate_state": {
                "aggressive_history": risk.get("aggressive_history", ""),
                "conservative_history": risk.get("conservative_history", ""),
                "neutral_history": risk.get("neutral_history", ""),
                "history": risk.get("history", ""),
                "judge_decision": risk.get("judge_decision", ""),
            },
            "investment_plan": final_state.get("investment_plan", ""),
            "final_trade_decision": final_state.get("final_trade_decision", ""),
        }

        # Save to file. Reject ticker values that would escape the
        # results directory when joined as a path component.
        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)

        # Drop the in-memory copy after the per-date JSON is written — nothing
        # else consumes log_states_dict, and it otherwise grows without bound (F7.4).
        self.log_states_dict.pop(str(trade_date), None)

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
