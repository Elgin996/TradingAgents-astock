"""Render the completed analysis report with expandable sections and PDF download."""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

import streamlit as st

from tradingagents.agents.utils.structured import has_freetext_marker
from web.pdf_export import generate_markdown, generate_pdf
from web.stock_display import normalize_stock_mentions, stock_display_label


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _signal_style(signal: str) -> tuple[str, str]:
    s = signal.upper()
    if "BUY" in s:
        return "#22c55e", "买入"
    if "SELL" in s:
        return "#ef4444", "卖出"
    return "#fbbf24", "持有"


_ANALYST_SECTIONS = [
    ("market_report", "📊 技术分析"),
    ("sentiment_report", "💬 市场情绪"),
    ("news_report", "📰 新闻舆情"),
    ("fundamentals_report", "📋 基本面"),
    ("policy_report", "🏛️ 政策分析"),
    ("hot_money_report", "🔥 游资追踪"),
    ("lockup_report", "🔒 解禁/减持"),
]
_ETF_ANALYST_SECTIONS = [
    ("market_report", "📊 ETF 技术分析"),
    ("etf_liquidity_report", "💧 流动性与交易"),
    ("etf_profile_report", "🏷️ ETF 结构、份额与规模"),
    ("etf_index_news_report", "📰 指数新闻与政策"),
    ("etf_compare_report", "⚖️ 同类比较与预警"),
]


def _safe_filename_label(label: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", label).strip("_")
    return cleaned or "report"


def _display_report_text(text: Any, ticker: str, final_state: dict[str, Any]) -> str:
    cleaned = _strip_think(str(text))
    return normalize_stock_mentions(cleaned, ticker, final_state)


_TECHNICAL_METADATA_FIELDS = {
    "symbol",
    "adjustment",
    "source",
    "source_symbol",
    "retrieved_at",
    "flags",
    "trade_date",
}
_TECHNICAL_INDICATOR_LABELS = {
    "close_sma_20": "收盘价 SMA20",
    "close_sma_50": "收盘价 SMA50",
    "close_sma_200": "收盘价 SMA200",
    "close_10_ema": "收盘价 EMA10",
    "macd": "MACD",
    "macds": "MACD 信号线",
    "macdh": "MACD 柱",
    "rsi": "RSI",
    "boll": "布林中轨",
    "boll_ub": "布林上轨",
    "boll_lb": "布林下轨",
    "atr": "ATR",
    "vwma": "成交量加权均线",
    "mfi": "MFI",
    "volume_5_sma": "成交量 SMA5",
    "volume_20_sma": "成交量 SMA20",
    "rolling_high_20": "20 日最高价",
    "rolling_low_20": "20 日最低价",
    "rolling_high_60": "60 日最高价",
    "rolling_low_60": "60 日最低价",
}
_TECHNICAL_SIGNAL_DIRECTION_LABELS = {
    "bullish": "看多",
    "bearish": "看空",
    "neutral": "中性",
    "unavailable": "不可得",
}


def _format_technical_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        formatted = f"{value:,.4f}".rstrip("0").rstrip(".")
        return formatted
    return str(value)


def _technical_indicator_rows(
    items: Any,
    *,
    scope: str,
) -> list[dict[str, str]]:
    """Normalize v1 and product-v2 indicator payloads for the report table."""
    rows: list[dict[str, str]] = []
    if isinstance(items, dict):
        normalized = [
            {"name": name, "value": value}
            for name, value in items.items()
        ]
    elif isinstance(items, list):
        normalized = [item for item in items if isinstance(item, dict)]
    else:
        normalized = []

    for item in normalized:
        name = str(item.get("name", "")).strip()
        value = item.get("value")
        if not name or name in _TECHNICAL_METADATA_FIELDS or value is None:
            continue
        rows.append(
            {
                "对象": scope,
                "指标": _TECHNICAL_INDICATOR_LABELS.get(name, name),
                "字段": name,
                "数值": _format_technical_value(value),
                "日期": str(item.get("trade_date", "")),
            }
        )
    return rows


def _render_structured_technical_evidence(final_state: dict[str, Any]) -> None:
    """Show the frozen indicator/signal evidence behind the technical report."""
    bundle = (
        final_state.get("product_technical_evidence_bundle")
        or final_state.get("technical_evidence_bundle")
        or {}
    )
    if not isinstance(bundle, dict):
        return

    subject_indicators = bundle.get("subject_indicators")
    if subject_indicators is None:
        subject_indicators = bundle.get("indicators")
    indicator_rows = _technical_indicator_rows(subject_indicators, scope="主体")
    indicator_rows.extend(
        _technical_indicator_rows(
            bundle.get("reference_indicators"),
            scope="参考",
        )
    )

    subject_signals = bundle.get("subject_signals")
    if subject_signals is None:
        subject_signals = bundle.get("signals")
    signal_rows: list[dict[str, str]] = []
    if isinstance(subject_signals, list):
        for signal in subject_signals:
            if not isinstance(signal, dict):
                continue
            direction = str(signal.get("direction", "unavailable"))
            signal_rows.append(
                {
                    "对象": "主体",
                    "信号": str(signal.get("signal_id", "")),
                    "类别": str(signal.get("category", "")),
                    "方向": _TECHNICAL_SIGNAL_DIRECTION_LABELS.get(direction, direction),
                    "强度": _format_technical_value(signal.get("strength", "")),
                    "置信度": _format_technical_value(signal.get("confidence", "")),
                }
            )
    reference_signals = bundle.get("reference_signals")
    if isinstance(reference_signals, list):
        for signal in reference_signals:
            if not isinstance(signal, dict):
                continue
            direction = str(signal.get("direction", "unavailable"))
            signal_rows.append(
                {
                    "对象": "参考",
                    "信号": str(signal.get("signal_id", "")),
                    "类别": str(signal.get("category", "")),
                    "方向": _TECHNICAL_SIGNAL_DIRECTION_LABELS.get(direction, direction),
                    "强度": _format_technical_value(signal.get("strength", "")),
                    "置信度": _format_technical_value(signal.get("confidence", "")),
                }
            )

    assessment = bundle.get("product_assessment") or final_state.get("technical_assessment") or {}
    if isinstance(assessment, dict) and assessment:
        st.caption(
            "确定性技术判断："
            f"{assessment.get('stance', assessment.get('subject_stance', 'unavailable'))} · "
            f"置信度 {_format_technical_value(assessment.get('confidence', ''))} · "
            f"数据质量 {assessment.get('data_quality_grade', '—')}"
        )

    market_bundle = final_state.get("analysis_market_data_bundle") or {}
    subject = market_bundle.get("subject") if isinstance(market_bundle, dict) else None
    bars = subject.get("bars") if isinstance(subject, dict) else None
    latest_bar = bars[-1] if isinstance(bars, list) and bars else None
    if latest_bar is None:
        latest_bar = bundle.get("latest_bar")
    if isinstance(latest_bar, dict) and latest_bar:
        st.markdown("**最新行情**")
        st.dataframe(
            [
                {
                    "日期": latest_bar.get("trade_date", ""),
                    "开盘": _format_technical_value(latest_bar.get("open", "")),
                    "最高": _format_technical_value(latest_bar.get("high", "")),
                    "最低": _format_technical_value(latest_bar.get("low", "")),
                    "收盘": _format_technical_value(latest_bar.get("close", "")),
                    "成交量": _format_technical_value(latest_bar.get("volume", "")),
                    "来源": latest_bar.get("source", ""),
                }
            ],
            hide_index=True,
            use_container_width=True,
        )

    if indicator_rows:
        st.markdown("**已验证技术指标**")
        st.dataframe(indicator_rows, hide_index=True, use_container_width=True)
    if signal_rows:
        st.markdown("**确定性技术信号**")
        st.dataframe(signal_rows, hide_index=True, use_container_width=True)


def _state_digest(final_state: dict[str, Any]) -> str:
    payload = json.dumps(final_state, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_pdf(state_digest: str, ticker: str, trade_date: str, signal: str, state_json: str) -> bytes:
    """Cache PDF bytes keyed on a stable digest of the final state (F6.7)."""
    del state_digest  # hash key only; content comes from state_json
    return generate_pdf(json.loads(state_json), ticker, trade_date, signal)


def render_report(
    final_state: dict[str, Any],
    ticker: str,
    trade_date: str,
    signal: str,
    elapsed: float | None = None,
) -> None:
    """Render the full analysis report."""

    color, cn_signal = _signal_style(signal)
    ticker_label = stock_display_label(ticker, final_state)
    safe_ticker_label = html.escape(ticker_label)
    safe_trade_date = html.escape(str(trade_date))
    safe_signal = html.escape(str(signal).upper())

    stats_html = ""
    if elapsed is not None:
        m, s = divmod(int(elapsed), 60)
        stats_html = f'<div style="font-size:0.9rem; color:#888; margin-top:0.3rem;">耗时 {m}:{s:02d}</div>'

    st.markdown(
        f"""
        <div style="
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border: 1px solid #333;
            border-radius: 16px;
            padding: 2rem;
            text-align: center;
            margin: 1rem 0 2rem;
        ">
            <div style="font-size:0.9rem; color:#888; letter-spacing:2px;">TRADING SIGNAL</div>
            <div style="font-size:3.5rem; font-weight:900; color:{color}; margin:0.3rem 0;">
                {safe_signal}
            </div>
            <div style="font-size:1.2rem; color:#f5f1eb;">
                {safe_ticker_label} · {safe_trade_date}
            </div>
            {stats_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption("⚠️ 本报告由 AI 自动生成，仅供学习研究，不构成投资建议。")
    market_quality = final_state.get("market_data_quality") or {}
    if isinstance(market_quality, dict) and market_quality:
        grade = html.escape(str(market_quality.get("grade", "F")))
        status = html.escape(str(market_quality.get("source_status", "UNKNOWN")))
        decision = html.escape(str(final_state.get("market_data_decision") or market_quality.get("decision", "block")))
        snapshot = html.escape(str(final_state.get("market_snapshot_id") or "unavailable"))
        alert = "#7f1d1d" if grade in {"C", "D", "F"} or decision == "block" else "#14532d"
        st.markdown(
            f'<div style="background:{alert}; padding:0.65rem 1rem; border-radius:8px; margin:0.5rem 0;">'
            f"数据质量：{grade} / {status} · 决策：{decision} · 快照：{snapshot}</div>",
            unsafe_allow_html=True,
        )
    if final_state.get("analysis_mode") == "etf":
        profile = final_state.get("instrument_profile") or {}
        analysis_product = final_state.get("analysis_product") or profile.get(
            "analysis_product", "passive_equity_etf"
        )
        product_label = {
            "passive_equity_etf": "被动股票指数 ETF",
            "active_equity_etf": "主动股票 ETF",
        }.get(analysis_product, "境内股票 ETF")
        reference_payload = profile.get("reference_instrument") or {}
        reference_name = (
            reference_payload.get("name")
            if isinstance(reference_payload, dict)
            else None
        ) or profile.get("tracking_index_name") or "未提供"
        reference_label = "比较基准" if analysis_product == "active_equity_etf" else "跟踪指数"
        st.caption(
            f"{product_label} · {reference_label}：{reference_name} · "
            f"能力：{', '.join(final_state.get('analysis_capabilities', []))}"
        )
        product_bundle = final_state.get("product_technical_evidence_bundle") or {}
        if product_bundle:
            assessment = product_bundle.get("product_assessment") or {}
            alignment = product_bundle.get("alignment") or {}
            st.info(
                "产品状态："
                f"{assessment.get('product_state', 'unavailable')} · "
                f"主体：{assessment.get('subject_stance', 'unavailable')} · "
                f"参考：{assessment.get('reference_stance', 'unavailable')} · "
                f"关系：{assessment.get('alignment_state', 'unavailable')} · "
                f"组合快照：{final_state.get('analysis_market_data_bundle', {}).get('bundle_snapshot_id', 'unavailable')}"
            )
            if alignment:
                st.caption(
                    "共同观察："
                    f"{alignment.get('common_observations', 0)} / "
                    f"coverage={alignment.get('common_coverage', 0)}"
                )
        shadow = final_state.get("technical_shadow_comparison") or {}
        if shadow:
            st.caption(
                "Shadow v1/v2："
                f"v1={shadow.get('legacy_stance', 'unavailable')} · "
                f"v2={shadow.get('v2_state', 'unavailable')} · "
                f"翻转={'是' if shadow.get('stance_flipped') else '否'}"
            )
        unavailable = final_state.get("analysis_unavailable_capabilities") or {}
        if unavailable:
            st.caption(
                "不可得数据："
                + "；".join(f"{name}（{reason}）" for name, reason in unavailable.items())
            )

    for key in (
        "final_trade_decision",
        "investment_plan",
        "trader_investment_plan",
    ):
        if has_freetext_marker(final_state.get(key, "") or ""):
            st.warning(
                "本次决策未通过结构化校验，评级为启发式解析，可能不准确"
            )
            break

    # Do not build exports while opening a history record.  Both exports walk
    # the complete state, and PDF generation may also inspect system fonts;
    # doing that synchronously here makes the report appear to hang.  Prepare
    # each file only when the user asks for it.
    digest = _state_digest(final_state)
    export_prefix = f"report_export_{digest}"
    col_md, col_pdf, col_spacer = st.columns([1, 1, 2])
    with col_md:
        md_key = f"{export_prefix}_markdown"
        if st.button("📥 准备 Markdown", key=f"{export_prefix}_markdown_prepare", use_container_width=True):
            st.session_state[md_key] = generate_markdown(
                final_state, ticker, trade_date, signal
            )
        md_text = st.session_state.get(md_key)
        if md_text:
            st.download_button(
                "⬇️ 下载 Markdown",
                data=md_text.encode("utf-8"),
                file_name=f"TradingAgents-Astock_{_safe_filename_label(ticker_label)}_{trade_date}.md",
                mime="text/markdown",
                key=f"{export_prefix}_markdown_download",
                use_container_width=True,
            )
    with col_pdf:
        pdf_key = f"{export_prefix}_pdf"
        pdf_error_key = f"{export_prefix}_pdf_error"
        if st.button("📄 准备 PDF", key=f"{export_prefix}_pdf_prepare", use_container_width=True):
            try:
                state_json = json.dumps(final_state, default=str, ensure_ascii=False)
                st.session_state[pdf_key] = _cached_pdf(
                    digest, ticker, trade_date, signal, state_json
                )
                st.session_state.pop(pdf_error_key, None)
            except Exception as exc:  # noqa: BLE001 — never let PDF crash the results page
                st.session_state[pdf_error_key] = str(exc)
        pdf_bytes = st.session_state.get(pdf_key)
        if pdf_bytes:
            st.download_button(
                "⬇️ 下载 PDF",
                data=pdf_bytes,
                file_name=f"TradingAgents-Astock_{_safe_filename_label(ticker_label)}_{trade_date}.pdf",
                mime="application/pdf",
                key=f"{export_prefix}_pdf_download",
                use_container_width=True,
            )
        elif st.session_state.get(pdf_error_key):
            st.button(
                "📄 PDF 不可用",
                disabled=True,
                use_container_width=True,
                help=(
                    "PDF 生成失败，请改用 Markdown 导出。原因："
                    + st.session_state[pdf_error_key]
                ),
            )

    st.markdown("---")

    inv_plan = final_state.get("investment_plan", "")
    if inv_plan:
        st.markdown("### 👔 最终投资建议")
        st.markdown(_display_report_text(inv_plan, ticker, final_state))
        st.markdown("---")

    st.markdown("### 📊 分析师报告")

    # Quality is the lens through which every analyst section should be read,
    # so keep it first rather than burying it after the decision chain.
    dqs = final_state.get("data_quality_summary", "")
    if dqs:
        with st.expander("✅ 数据质量", expanded=True):
            st.markdown(_display_report_text(dqs, ticker, final_state))

    sections = (
        _ETF_ANALYST_SECTIONS
        if final_state.get("analysis_mode") == "etf"
        else _ANALYST_SECTIONS
    )
    if final_state.get("analysis_mode") == "etf":
        from tradingagents.dataflows.analysis_capabilities import report_field_is_active

        capabilities = final_state.get("analysis_capabilities")
        sections = [
            (key, title)
            for key, title in sections
            if report_field_is_active(key, capabilities)
        ]
    for key, title in sections:
        content = final_state.get(key, "")
        if not content:
            continue
        with st.expander(title, expanded=(key == "market_report")):
            st.markdown(_display_report_text(content, ticker, final_state))
            if key == "market_report":
                _render_structured_technical_evidence(final_state)

    debate = final_state.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        st.markdown("### ⚔️ 多空辩论")
        tab_bull, tab_bear, tab_judge = st.tabs(["多方", "空方", "研究经理"])
        with tab_bull:
            st.markdown(_display_report_text(debate.get("bull_history", "") or "无数据", ticker, final_state))
        with tab_bear:
            st.markdown(_display_report_text(debate.get("bear_history", "") or "无数据", ticker, final_state))
        with tab_judge:
            st.markdown(_display_report_text(debate.get("judge_decision", "") or "无数据", ticker, final_state))

    trader_decision = final_state.get("trader_investment_decision", "")
    if trader_decision:
        with st.expander("💹 交易员决策", expanded=False):
            st.markdown(_display_report_text(trader_decision, ticker, final_state))

    risk = final_state.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        st.markdown("### 🛡️ 风控评估")
        tab_agg, tab_con, tab_neu, tab_rj = st.tabs(["激进", "保守", "中性", "风控决策"])
        with tab_agg:
            st.markdown(_display_report_text(risk.get("aggressive_history", "") or "无数据", ticker, final_state))
        with tab_con:
            st.markdown(_display_report_text(risk.get("conservative_history", "") or "无数据", ticker, final_state))
        with tab_neu:
            st.markdown(_display_report_text(risk.get("neutral_history", "") or "无数据", ticker, final_state))
        with tab_rj:
            st.markdown(_display_report_text(risk.get("judge_decision", "") or "无数据", ticker, final_state))
