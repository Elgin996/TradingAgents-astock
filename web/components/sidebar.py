"""Sidebar: stock input, LLM config, and history list."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import streamlit as st

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.checkpointer import clear_checkpoint
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS
from web.history import (
    clear_incomplete_task,
    get_history,
    get_incomplete_history,
    record_incomplete_task,
)
from web.model_history import get_used_models

# Provider display names in recommended order
_PROVIDERS: list[tuple[str, str]] = [
    ("MiniMax（推荐·国内直连）", "minimax"),
    ("DeepSeek", "deepseek"),
    ("通义千问 Qwen", "qwen"),
    ("智谱 GLM", "glm"),
    ("OpenAI", "openai"),
    ("Anthropic", "anthropic"),
    ("Google Gemini", "google"),
    ("xAI Grok", "xai"),
    ("OpenRouter（聚合·填 vendor/model 形式 ID）", "openrouter"),
    ("OpenAI 兼容（自定义 base_url·9Router/AI Router/自建代理）", "openai_compatible"),
    ("Ollama（本地）", "ollama"),
]

_PROVIDER_DISPLAY = [name for name, _ in _PROVIDERS]
_PROVIDER_KEYS = [key for _, key in _PROVIDERS]


_EXCHANGE_CN = {"SSE": "上交所", "SZSE": "深交所"}


def _format_price_limit_caption(profile: dict[str, Any]) -> str:
    limit = profile.get("price_limit_pct")
    if isinstance(limit, dict):
        value = limit.get("value", 10)
        status = limit.get("status", "assumed")
    else:
        value = 10
        status = "assumed"
    status_cn = {
        "derived": "推导",
        "assumed": "假定",
        "ok": "确认",
    }.get(str(status), str(status))
    return f"涨跌幅 {value}%（{status_cn}）"


def _history_mode_badge(entry: dict[str, Any]) -> str:
    """Compact mode badge for history / incomplete task rows."""
    mode = entry.get("analysis_mode") or "stock"
    if mode == "etf":
        product = entry.get("analysis_product")
        if product == "active_equity_etf":
            return "[主动ETF]"
        if product == "passive_equity_etf":
            return "[被动ETF]"
        return "[ETF]"
    return "[个股]"


def _history_mode_detail(entry: dict[str, Any]) -> str:
    """Show the analyzed stock/ETF name, never the ETF's index name."""
    name = entry.get("name") or ""
    profile = entry.get("instrument_profile") or {}
    if not name and isinstance(profile, dict):
        name = profile.get("name") or profile.get("fund_name") or ""
    return f" · {name}" if name else ""


def _tracking_index_display(profile: dict[str, Any]) -> tuple[str | None, str | None, str]:
    """Return (code, provider, source_status) from flat or frozen profile shapes."""
    raw = profile.get("tracking_index_code")
    provider = profile.get("tracking_index_provider")
    status = str(profile.get("tracking_index_code_status") or "missing")
    if isinstance(raw, dict):
        value = raw.get("value")
        if isinstance(value, dict):
            code = value.get("code")
            provider = value.get("provider") or provider
        else:
            code = value
        status = str(raw.get("notes") or status)
        return (str(code) if code else None), (str(provider) if provider else None), status
    if raw:
        return str(raw), (str(provider) if provider else None), status
    return None, None, status


def _history_mode_label(entry: dict[str, Any]) -> str:
    return f"{_history_mode_badge(entry)}{_history_mode_detail(entry)}"


def _resolve_user_input(raw: str) -> tuple[str, str | None]:
    """Resolve raw user input to (ticker_code, error_msg).

    Accepts 6-digit codes or Chinese stock names (e.g. '宝光股份').
    Returns (code, None) on success or ("", error_msg) on failure.
    """
    from tradingagents.dataflows.a_stock import resolve_ticker
    from tradingagents.dataflows.instrument_store import find_instrument_by_name

    try:
        if any("一" <= ch <= "鿿" for ch in raw):
            saved = find_instrument_by_name(DEFAULT_CONFIG["data_cache_dir"], raw)
            if saved:
                return str(saved["symbol"]), None
        code = resolve_ticker(raw)
        return code, None
    except ValueError as e:
        return "", str(e)


def _resolve_instrument_profile(code: str) -> tuple[str, dict[str, Any] | None, str | None]:
    """Return the mode and a recognized ETF profile when one is available."""
    from tradingagents.dataflows.instrument_store import get_instrument

    saved = get_instrument(DEFAULT_CONFIG["data_cache_dir"], code)
    if saved and saved.get("security_type") == "etf" and saved.get("profile"):
        return "etf", saved["profile"], None

    from tradingagents.dataflows.a_stock import resolve_a_share_exchange
    from tradingagents.dataflows.security_master import resolve_fund_master

    try:
        # The checkbox already establishes that this is an ETF. Derive the
        # exchange from the six-digit code instead of probing mootdx TCP 7709.
        record = resolve_fund_master(
            code, exchange=resolve_a_share_exchange(code)
        )
    except ValueError as exc:
        # Any parse/lookup failure (Eastmoney profile page changed, code
        # absent from the securities master, etc.) is ambiguous and must not
        # be inferred as "stock" from a code prefix. Surface as unknown so
        # the user can retry rather than silently mis-routing the analysis.
        return "unknown", None, f"证券主数据无法确认类型：{exc}"
    except Exception as exc:
        return "unknown", None, f"证券主数据暂不可用，请重试：{exc}"

    if record.classification in {"domestic_equity_etf", "active_equity_etf"}:
        from tradingagents.dataflows.instrument import profile_from_fund_master

        profile = profile_from_fund_master(record).to_dict()
        return "etf", profile, None
    if record.classification == "unsupported_fund":
        return "unsupported", None, f"当前版本不支持该类型：{record.classification_reason}"
    # "not_a_fund": the Eastmoney fund-profile page returned placeholder
    # fields, confirming this is an ordinary listed equity, not a fund. V2
    # routing requires a frozen stock profile just like the ETF path.
    from tradingagents.dataflows.instrument import profile_for_stock

    if record.exchange is None:
        return "unknown", None, "证券主数据无法确认普通股票所属交易所"
    return "stock", profile_for_stock(code, exchange=record.exchange).to_dict(), None


def _resolve_stock_profile(code: str) -> tuple[str, dict[str, Any] | None, str | None]:
    """Build a stock profile locally without querying the securities master.

    The user has already identified the instrument type with the ETF checkbox,
    so ordinary stocks do not need the mootdx-backed exchange membership
    lookup.  Exchange is derived from the A-share code prefix, which is enough
    for routing the stock data adapters.
    """
    from tradingagents.dataflows.a_stock import resolve_a_share_exchange
    from tradingagents.dataflows.instrument_store import get_instrument
    from tradingagents.dataflows.instrument import profile_for_stock

    try:
        saved = get_instrument(DEFAULT_CONFIG["data_cache_dir"], code)
        if saved and saved.get("security_type") == "stock" and saved.get("profile"):
            return "stock", saved["profile"], None
        exchange = resolve_a_share_exchange(code)
        profile = profile_for_stock(code, exchange=exchange).to_dict()
        return "stock", profile, None
    except Exception as exc:
        return "unknown", None, f"股票代码无法识别：{exc}"


def _apply_user_tracking_index(
    profile: dict[str, Any],
    *,
    code: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Freeze a user-confirmed index code and infer its publisher."""
    from tradingagents.dataflows.index_catalog import infer_tracking_index_provider
    from tradingagents.dataflows.security_master import (
        FundMasterRecord,
        with_user_supplied_tracking_index_code,
    )
    from tradingagents.dataflows.instrument import DataPoint, utc_now

    try:
        record = FundMasterRecord(
            symbol=profile["symbol"],
            exchange=profile["exchange"],
            fund_name=profile["fund_name"],
            fund_type="指数型-股票",
            tracking_index_name=profile["tracking_index_name"],
            fund_manager=None,
            listed_or_established_date=None,
            management_fee=None,
            custodian_fee=None,
            classification="domestic_equity_etf",
            classification_reason="已由证券主数据确认",
        )
        provider = infer_tracking_index_provider(
            code, profile.get("tracking_index_name")
        )
        updated = with_user_supplied_tracking_index_code(
            record, code=code, provider=provider
        )
    except (KeyError, ValueError) as exc:
        return None, str(exc)

    frozen = dict(profile)
    frozen["tracking_index_code"] = DataPoint(
        value={
            "code": updated.tracking_index_code,
            "provider": updated.tracking_index_provider,
        },
        unit=None,
        as_of=None,
        retrieved_at=utc_now(),
        source="user",
        status="ok",
        notes="user_supplied",
    ).to_dict()
    from tradingagents.dataflows.index_master import resolve_index_reference

    reference = resolve_index_reference(
        name=frozen.get("tracking_index_name"),
        code=updated.tracking_index_code,
        provider=updated.tracking_index_provider,
        role="tracking_index",
        user_supplied=True,
    )
    frozen["reference_instrument"] = reference.model_dump(mode="json")
    return frozen, None


def _clear_analysis_artifacts(
    ticker: str,
    trade_date: str,
    analysis_mode: str = "stock",
    analysis_product: str | None = None,
) -> None:
    clear_incomplete_task(ticker, trade_date, analysis_mode, analysis_product)
    clear_checkpoint(
        DEFAULT_CONFIG["data_cache_dir"],
        ticker,
        trade_date,
        analysis_mode,
        f"{analysis_product}-v2" if analysis_product else None,
    )


def _clear_conflicting_mode_artifacts(
    ticker: str, trade_date: str, analysis_mode: str
) -> None:
    """Drop same-ticker/date artifacts from the opposite analysis mode."""
    other_mode = "stock" if analysis_mode == "etf" else "etf"
    _clear_analysis_artifacts(ticker, trade_date, other_mode)


def _render_analysis_controls(raw_ticker: str, trade_date_value: date) -> None:
    tracker = st.session_state.get("tracker")
    is_running = tracker is not None and tracker.is_running
    trade_date = trade_date_value.strftime("%Y-%m-%d")

    pause_col, resume_col, stop_col = st.columns(3)

    pause_disabled = not is_running or tracker.is_paused or tracker.stop_requested
    if pause_col.button(
        "暂停",
        key="sidebar_pause_analysis",
        use_container_width=True,
        disabled=pause_disabled,
    ):
        if tracker.pause():
            record_incomplete_task(
                tracker.ticker,
                tracker.trade_date,
                status="paused",
                completed_stages=tracker.completed_stages,
                analysis_mode=tracker.analysis_mode,
                analysis_product=tracker.analysis_product,
                instrument_profile=tracker.instrument_profile,
            )
        st.rerun()

    resume_disabled = not is_running or not tracker.is_paused or tracker.stop_requested
    if resume_col.button(
        "恢复",
        key="sidebar_resume_analysis",
        use_container_width=True,
        disabled=resume_disabled,
    ):
        if tracker.resume():
            record_incomplete_task(
                tracker.ticker,
                tracker.trade_date,
                status="running",
                completed_stages=tracker.completed_stages,
                analysis_mode=tracker.analysis_mode,
                analysis_product=tracker.analysis_product,
                instrument_profile=tracker.instrument_profile,
            )
        st.rerun()

    can_stop = tracker is not None or bool(raw_ticker.strip())
    if stop_col.button(
        "停止",
        key="sidebar_stop_analysis",
        use_container_width=True,
        disabled=not can_stop,
    ):
        target_ticker = tracker.ticker if tracker is not None and tracker.ticker else ""
        target_date = (
            tracker.trade_date
            if tracker is not None and tracker.trade_date
            else trade_date
        )

        if not target_ticker:
            target_ticker, err = _resolve_user_input(raw_ticker)
            if err:
                st.error(f"❌ {err}")
                return

        if tracker is not None and tracker.is_running:
            tracker.request_stop()
            clear_incomplete_task(
                target_ticker, target_date, tracker.analysis_mode
            )
        else:
            if tracker is not None:
                tracker.mark_stopped()
                st.session_state["tracker"] = None
            _clear_analysis_artifacts(
                target_ticker,
                target_date,
                tracker.analysis_mode if tracker is not None else "stock",
                tracker.analysis_product if tracker is not None else None,
            )

        st.session_state["viewing_history"] = None
        st.success("已清空当前进度；下一次开始分析会从头生成。")
        st.rerun()

    if tracker is not None and tracker.stop_requested:
        st.caption("正在停止并清空，收尾完成后可重新开始。")


def _render_llm_config() -> None:
    """Render LLM provider and model selection controls."""

    configured_provider = os.getenv(
        "TRADINGAGENTS_LLM_PROVIDER", DEFAULT_CONFIG["llm_provider"]
    ).strip().lower()
    provider_default = (
        _PROVIDER_KEYS.index(configured_provider)
        if configured_provider in _PROVIDER_KEYS
        else 0
    )

    provider_idx = st.selectbox(
        "LLM 供应商",
        range(len(_PROVIDERS)),
        index=provider_default,
        format_func=lambda i: _PROVIDER_DISPLAY[i],
        key="llm_provider_idx",
        help="选择你配置了 API Key 的供应商",
    )
    provider_key = _PROVIDER_KEYS[provider_idx]
    st.session_state["llm_provider"] = provider_key

    def render_model_select(role: str, label: str, env_name: str, help_text: str) -> str:
        configured = os.getenv(env_name, DEFAULT_CONFIG[f"{role}_think_llm"])
        catalog = MODEL_OPTIONS.get(provider_key, {}).get(role, [])
        labels = {value: title for title, value in catalog if value != "custom"}
        catalog_values = [value for _, value in catalog if value != "custom"]
        preferred = (
            configured
            if provider_key == configured_provider or not catalog_values
            else catalog_values[0]
        )
        choices: list[str] = []
        for value in (
            preferred,
            *catalog_values,
            *get_used_models(provider_key, role),
        ):
            value = str(value).strip()
            if value and value not in choices:
                choices.append(value)
        return st.selectbox(
            label,
            choices,
            format_func=lambda value: labels.get(value, f"曾用/自定义 · {value}"),
            key=f"{role}_model_id_select_{provider_key}",
            help=help_text + "；可输入新 ID，成功用于分析后会保留在下拉菜单中。",
            accept_new_options=True,
        )

    st.session_state["quick_think_llm"] = render_model_select(
        "quick",
        "快速思考模型 ID",
        "TRADINGAGENTS_QUICK_THINK_LLM",
        "用于常规分析任务，速度优先",
    )
    st.session_state["deep_think_llm"] = render_model_select(
        "deep",
        "深度思考模型 ID",
        "TRADINGAGENTS_DEEP_THINK_LLM",
        "用于辩论/决策等需要深度推理的任务",
    )

    if provider_key == "openrouter":
        effort_values = ["", "none", "minimal", "low", "medium", "high", "xhigh", "max"]
        effort_labels = ["使用模型默认值", "关闭推理", "Minimal", "Low", "Medium", "High", "XHigh", "Max"]
        configured_effort = os.getenv("TRADINGAGENTS_REASONING_EFFORT", "").strip().lower()
        effort_default = effort_values.index(configured_effort) if configured_effort in effort_values else 0
        effort_idx = st.selectbox(
            "推理 Effort",
            range(len(effort_values)),
            index=effort_default,
            format_func=lambda i: effort_labels[i],
            key="openrouter_reasoning_effort_idx",
            help="仅在模型支持推理时生效。更高 Effort 会增加推理 token 用量与成本。",
        )
        st.session_state["openrouter_reasoning_effort"] = effort_values[effort_idx] or None

    base_url_required = provider_key == "openai_compatible"
    st.text_input(
        "API Base URL（第三方/代理" + ("·必填" if base_url_required else "，可选") + "）",
        key="llm_base_url",
        placeholder="例: https://your-relay.example/v1",
        help=(
            "通过第三方中转/代理访问模型时填写网关地址；留空则用所选供应商的官方地址。"
            "API Key 仍从 .env 读取，每个供应商用各自的环境变量——"
            "OpenAI=OPENAI_API_KEY、DeepSeek=DEEPSEEK_API_KEY、"
            "通义=DASHSCOPE_API_KEY、智谱=ZHIPU_API_KEY、MiniMax=MINIMAX_API_KEY、"
            "Claude=ANTHROPIC_API_KEY、OpenRouter=OPENROUTER_API_KEY、xAI=XAI_API_KEY、"
            "OpenAI 兼容（自定义）=OPENAI_COMPATIBLE_API_KEY（也接受 OPENAI_API_KEY）。"
            "也可在 .env 里设 BACKEND_URL 代替此处。"
        ),
    )
    if base_url_required:
        st.caption(
            "已选「OpenAI 兼容（自定义）」：**Base URL 必填**（你的网关，走标准 Chat "
            "Completions），模型 ID 手动填写，Key 在 .env 设 `OPENAI_COMPATIBLE_API_KEY`。"
        )

    # ── 个人 Claude 订阅额度（可选，仅个人自用）────────────────────────
    _scope_labels = [
        "关闭（走上面选的供应商）",
        "仅深度节点（Research/Portfolio）",
        "所有节点（含 7 个工具分析师）",
    ]
    _scope_values = ["off", "deep", "all"]
    scope_idx = st.selectbox(
        "个人 Claude 订阅覆盖 (Agent SDK)",
        range(len(_scope_labels)),
        format_func=lambda i: _scope_labels[i],
        key="subscription_scope_idx",
        help=(
            "让部分/全部节点经 Claude Agent SDK 走你个人 Pro/Max 订阅额度，"
            "而非按 token 计费。「所有节点」含 7 个工具分析师（其工具调用已桥接到订阅）。"
            "需装 [agentsdk] 依赖，且本机 claude 已登录（或设 CLAUDE_CODE_OAUTH_TOKEN）。"
        ),
    )
    scope = _scope_values[scope_idx]
    st.session_state["subscription_scope"] = scope
    if scope != "off":
        # 用别名而非写死版本号：claude CLI 的 opus/sonnet 恒指向最新模型。
        st.session_state.setdefault("agent_sdk_model", "opus")
        st.text_input(
            "订阅使用的 Claude 模型",
            key="agent_sdk_model",
            help=(
                "填别名 opus / sonnet（恒指向最新模型，推荐）或完整模型 id。"
                "撞额度/失败时自动降级到上面选的供应商 + 对应模型。"
            ),
        )
        if scope == "all":
            st.caption(
                "⚠️ 「所有节点」会把 7 个分析师 + 多空/交易员/风险辩手全部压到订阅上，"
                "订阅是按额度限流的，跑几轮就可能撞上限。可在 config 里把 "
                "`agent_sdk_quick_model` 设为 `sonnet` 降低消耗（默认已是）。"
            )
        if os.getenv("ANTHROPIC_API_KEY"):
            st.info(
                "检测到 ANTHROPIC_API_KEY。它**不会**泄进 Agent SDK 子进程"
                "（已在子进程环境显式置空），所以订阅额度照常生效；"
                "父进程保留它，是为了让 `anthropic` 仍能作为撞额度后的降级 provider。"
                "如果你并不打算保留付费降级，可在 .env 里清掉它。"
            )


def render_sidebar() -> None:
    """Render the sidebar with input controls and history."""

    st.markdown(
        """
        <div style="text-align:center; margin-bottom:1.5rem;">
            <span style="font-size:2rem; font-weight:800; color:#ff5a1f;">Trading</span><span style="font-size:2rem; font-weight:800; color:#f5f1eb;">Agents</span><span style="font-size:2rem; font-weight:800; color:#f5f1eb;">-</span><span style="font-size:2rem; font-weight:800; color:#ff5a1f;">Astock</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("#### 新建分析")

    ticker = st.text_input(
        "证券代码或名称",
        placeholder="例: 300750、510300 或 宁德时代",
        key="input_ticker",
        help="输入6位A股/ETF代码或中文证券全称",
    )
    is_etf = st.checkbox(
        "这是 ETF",
        key="input_is_etf",
        help="勾选后按 ETF 处理；不勾选则按普通股票处理。普通股票不会查询 mootdx 证券主数据。",
    )

    trade_date = st.date_input(
        "分析日期",
        value=date.today(),
        max_value=date.today(),
        key="input_date",
    )

    start_date = st.date_input(
        "数据起始日期",
        value=trade_date.replace(day=1),   # 默认本月第一天
        max_value=trade_date,
        key="input_start_date",
        help="技术分析回溯到该日期（默认本月第一天）。分析区间 = 起始日期 → 分析日期，"
             "用于「按月」或自定义时段分析；留默认即分析当月至今。",
    )
    # 分析窗口天数 → market_lookback_days（下限 5 天，保证指标有意义）
    st.session_state["market_lookback_days"] = max((trade_date - start_date).days, 5)
    if start_date >= trade_date:
        st.caption("⚠️ 起始日期应早于分析日期，已按最小窗口（5 天）处理。")

    with st.expander("⚙️ 模型配置", expanded=False):
        _render_llm_config()

    tracker = st.session_state.get("tracker")
    is_busy = tracker is not None and tracker.is_running
    is_stopping = is_busy and tracker.stop_requested
    resolved_code, input_error = _resolve_user_input(ticker) if ticker.strip() else ("", None)
    analysis_mode = "stock"
    analysis_product = "a_share_stock"
    instrument_profile: dict[str, Any] | None = None
    instrument_error: str | None = None
    if resolved_code:
        cache = st.session_state.setdefault("resolved_instrument_profiles", {})
        cache_key = (
            resolved_code,
            trade_date.strftime("%Y-%m-%d"),
            "etf" if is_etf else "stock",
        )
        cached = cache.get(cache_key)
        if cached is None:
            cached = (
                _resolve_instrument_profile(resolved_code)
                if is_etf
                else _resolve_stock_profile(resolved_code)
            )
            # Cache confirmed profiles only. A transient master-data timeout
            # must remain retryable on the next Streamlit rerun.
            if cached[2] is None:
                cache[cache_key] = cached
        analysis_mode, instrument_profile, instrument_error = cached
        if instrument_profile:
            analysis_product = instrument_profile.get(
                "analysis_product",
                "passive_equity_etf" if analysis_mode == "etf" else "a_share_stock",
            )

    if input_error:
        st.caption(f"❌ {input_error}")
    elif instrument_error:
        st.error(f"❌ {instrument_error}")
    elif analysis_mode == "etf" and instrument_profile is not None:
        exchange_cn = _EXCHANGE_CN.get(
            instrument_profile["exchange"], instrument_profile["exchange"]
        )
        fund_name = instrument_profile.get("fund_name") or instrument_profile.get(
            "symbol", resolved_code
        )
        product_label = (
            "主动股票 ETF"
            if analysis_product == "active_equity_etf"
            else "被动股票指数 ETF"
        )
        st.success(f"识别为 {product_label} · {fund_name} · {exchange_cn}")
        limit_caption = _format_price_limit_caption(instrument_profile)
        reference_payload = instrument_profile.get("reference_instrument") or {}
        index_name = (
            reference_payload.get("name")
            if isinstance(reference_payload, dict)
            else None
        ) or instrument_profile.get("tracking_index_name") or "未提供"
        relation_label = "比较基准" if analysis_product == "active_equity_etf" else "跟踪指数"
        st.caption(f"{relation_label} {index_name} · T+1 · {limit_caption}")
        index_code, index_provider, index_status = _tracking_index_display(
            instrument_profile
        )
        if analysis_product == "active_equity_etf":
            st.caption("主动管理产品：不使用机械跟踪一致性；比较基准仅作为相对强弱背景。")
        elif index_code is None:
            st.caption("指数代码未提供（可选）；不填写也可分析 ETF 自身数据。")
            user_index_code = st.text_input(
                "跟踪指数代码（可选）",
                key="etf_tracking_index_code",
                placeholder="例: 000300",
                help="仅在数据源支持该代码时用于指数行情对比；不影响 ETF 自身分析。",
            )
            if user_index_code:
                instrument_profile, instrument_error = _apply_user_tracking_index(
                    instrument_profile,
                    code=user_index_code,
                )
                if instrument_error:
                    st.caption(f"❌ {instrument_error}")
        else:
            status_cn = {
                "catalog": "目录映射",
                "user_supplied": "用户确认",
                "missing": "缺失",
            }.get(index_status, index_status)
            st.caption(
                f"指数代码：{index_provider or '未知供应方'} · {index_code}"
                f"（{status_cn}；点击开始即确认）"
            )
    elif resolved_code:
        st.success(f"识别为 股票 · {resolved_code}")

    start_disabled = (
        is_busy
        or not ticker
        or input_error is not None
        or instrument_error is not None
        or analysis_mode == "unsupported"
        or analysis_mode == "unknown"
        or (analysis_mode == "etf" and instrument_profile is None)
    )

    if st.button(
        "开始分析" if not is_busy else "停止中..." if is_stopping else "分析进行中...",
        use_container_width=True,
        disabled=start_disabled,
        type="primary",
    ):
        if resolved_code != ticker.strip():
            st.success(f"✅ {ticker.strip()} → {resolved_code}")
        st.session_state["start_analysis"] = {
            "ticker": resolved_code,
            "trade_date": trade_date.strftime("%Y-%m-%d"),
            "analysis_mode": analysis_mode,
            "analysis_product": analysis_product,
            "instrument_profile": instrument_profile,
            "fresh": True,
            "clear_other_mode": True,
        }
        st.session_state["viewing_history"] = None

    _render_analysis_controls(ticker, trade_date)

    st.markdown("---")
    st.markdown("#### 未完成任务")

    incomplete = get_incomplete_history()
    if not incomplete:
        st.caption("暂无未完成任务")
    else:
        for entry in incomplete[:10]:
            t, d = entry["ticker"], entry["trade_date"]
            status_label = {
                "error": "出错",
                "paused": "已暂停",
                "running": "进行中",
            }.get(entry.get("status"), "可继续")
            step = entry.get("checkpoint_step")
            step_label = f" · step {step}" if step is not None else ""
            mode_label = _history_mode_label(entry)
            label = f"{t}  ·  {d}  ·  {mode_label}  ·  {status_label}{step_label}"
            st.caption(label)
            resume_col, delete_col = st.columns([3, 2])
            task_key = (
                f"{t}_{d}_{entry.get('analysis_mode', 'stock')}_"
                f"{entry.get('analysis_product') or 'legacy'}"
            )
            if resume_col.button(
                "▶️ 继续",
                key=f"resume_{task_key}",
                use_container_width=True,
                disabled=is_busy,
            ):
                st.session_state["start_analysis"] = {
                    "ticker": t,
                    "trade_date": d,
                    "analysis_mode": entry.get("analysis_mode", "stock"),
                    "analysis_product": entry.get("analysis_product"),
                    "instrument_profile": entry.get("instrument_profile"),
                }
                st.session_state["viewing_history"] = None
            if delete_col.button(
                "🗑️ 删除",
                key=f"delete_{task_key}",
                use_container_width=True,
                disabled=is_busy,
            ):
                _clear_analysis_artifacts(
                    t,
                    d,
                    entry.get("analysis_mode", "stock"),
                    entry.get("analysis_product"),
                )
                current = st.session_state.get("tracker")
                if (
                    current is not None
                    and current.ticker == t
                    and current.trade_date == d
                    and not current.is_running
                ):
                    st.session_state["tracker"] = None
                st.session_state["viewing_history"] = None
                st.rerun()

    st.markdown("---")
    st.markdown("#### 历史记录")

    history = get_history()
    if not history:
        st.caption("暂无历史记录")
        return
    if is_busy:
        st.caption("当前分析仍在后台运行；查看历史记录不会中断当前分析。")

    for entry in history[:20]:
        t, d = entry["ticker"], entry["date"]
        mode = entry.get("analysis_mode") or "stock"
        mode_label = _history_mode_label(entry)
        label = f"{t}  ·  {d}  ·  {mode_label}"
        if st.button(
            label,
            key=f"hist_{t}_{d}_{mode}",
            use_container_width=True,
        ):
            st.session_state["viewing_history"] = entry["path"]
            st.session_state["start_analysis"] = None
            # Explicitly switch the main-area state now. This is important
            # while a progress fragment is polling in the same session: the
            # ordinary widget rerun can otherwise leave the old progress view
            # visible until the next poll.
            st.rerun()

    st.markdown("---")
    st.caption("⚠️ 仅供学习研究，不构成投资建议")
