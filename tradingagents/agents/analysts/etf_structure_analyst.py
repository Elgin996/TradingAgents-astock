"""Deterministically grounded ETF identity and disclosed structure report."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_utils import get_etf_profile, get_etf_shares_aum
from tradingagents.dataflows.vendors.base import VendorError


def _value(point: object):
    return point.get("value") if isinstance(point, dict) else None


def _render_grounded_structure_report(
    *,
    ticker: str,
    trade_date: str,
    instrument_profile: dict,
    profile_text: str,
    shares_text: str,
) -> str:
    try:
        profile = json.loads(profile_text)
    except (json.JSONDecodeError, TypeError):
        profile = {}
    try:
        shares_point = json.loads(shares_text).get("shares_and_aum", {})
    except (json.JSONDecodeError, TypeError):
        shares_point = {}
    rows = _value(shares_point)
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    reference = instrument_profile.get("reference_instrument") or {}
    points = {
        "基金名称": _value(profile.get("fund_name")) or instrument_profile.get("fund_name"),
        "基金管理人": _value(profile.get("fund_manager")),
        "跟踪指数": _value(profile.get("tracking_index_name")) or reference.get("name"),
        "指数代码": reference.get("code"),
        "指数供应方标识": reference.get("provider"),
        "指数序列口径": reference.get("series_variant"),
        "管理费率": _value(profile.get("management_fee")),
        "托管费率": _value(profile.get("custodian_fee")),
    }
    lines = [
        "## ETF 结构、份额与规模",
        "",
        f"标的：{ticker}；分析日期：{trade_date}。本节仅渲染基金档案与定期披露工具字段，不扩写供应方名称。",
        "",
        "### 基金身份与费用",
        "",
        "| 项目 | 工具返回值 |",
        "| --- | --- |",
    ]
    lines.extend(f"| {label} | {value if value is not None else '不可得'} |" for label, value in points.items())
    lines.extend(
        [
            "",
            "### 份额与 AUM 定期披露",
            "",
            "| 日期 | 期末总份额（亿份） | 期末净资产（亿元） | 期间申购（亿份） | 期间赎回（亿份） | 净资产变动率 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    if rows:
        for row in rows:
            lines.append(
                f"| {row.get('日期', '不可得')} | {row.get('期末总份额（亿份）', '不可得')} | "
                f"{row.get('期末净资产（亿元）', '不可得')} | {row.get('期间申购（亿份）', '不可得')} | "
                f"{row.get('期间赎回（亿份）', '不可得')} | {row.get('净资产变动率', '不可得')} |"
            )
    else:
        lines.append("| — | — | — | — | — | 工具未返回定期披露记录 |")
    lines.extend(
        [
            "",
            "### 口径与来源",
            "",
            "- 基金身份与费率来源：Eastmoney FundF10；指数代码、供应方标识和序列口径来自冻结的 InstrumentProfile。",
            f"- 份额/AUM 来源：{shares_point.get('source', '不可得') if isinstance(shares_point, dict) else '不可得'}；as_of：{shares_point.get('as_of', '不可得') if isinstance(shares_point, dict) else '不可得'}。",
            "- 份额、AUM、期间申购/赎回均是对应披露期的基金字段，不是实时净申赎，也不从当前价格反推。",
            "- 本节不推断指数供应方全称、不讨论公司盈利或管理层个股逻辑。",
        ]
    )
    return "\n".join(lines)


def create_etf_structure_analyst(llm):
    """Analyze ETF identity and disclosed structure without LLM-added facts."""
    del llm

    def node(state):
        ticker, trade_date = state["company_of_interest"], state["trade_date"]
        try:
            profile_text = get_etf_profile.func(ticker)
        except VendorError as exc:
            profile_text = json.dumps(
                {"profile": {"value": None, "status": "error", "notes": str(exc)}},
                ensure_ascii=False,
            )
        try:
            shares_text = get_etf_shares_aum.func(ticker)
        except VendorError as exc:
            shares_text = json.dumps(
                {"shares_and_aum": {"value": None, "status": "error", "notes": str(exc)}},
                ensure_ascii=False,
            )
        report = _render_grounded_structure_report(
            ticker=ticker,
            trade_date=trade_date,
            instrument_profile=state.get("instrument_profile") or {},
            profile_text=profile_text,
            shares_text=shares_text,
        )
        return {"messages": [AIMessage(content=report)], "etf_profile_report": report}

    return node
