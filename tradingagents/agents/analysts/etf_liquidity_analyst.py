import csv
import json
import re
from datetime import date, timedelta
from io import StringIO

from langchain_core.messages import AIMessage, ToolMessage

from tradingagents.agents.utils.agent_utils import (
    get_etf_quote,
    get_stock_data,
)
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.vendors.base import VendorError


def _tool_payloads(messages) -> dict[str, str]:
    return {
        str(message.name or ""): str(message.content or "")
        for message in messages
        if isinstance(message, ToolMessage)
    }


def _render_grounded_liquidity_report(messages, ticker: str, trade_date: str) -> str | None:
    """Render only tool-returned quote and deterministic OHLCV statistics."""
    payloads = _tool_payloads(messages)
    history = payloads.get("get_stock_data")
    quote_text = payloads.get("get_etf_quote")
    if not history and not quote_text:
        return None

    stats: dict[str, str] = {}
    latest_volume = None
    if history:
        for label, value in re.findall(r"^# Deterministic ([^:]+): (.+)$", history, re.MULTILINE):
            stats[label] = value.strip()
        csv_lines = [line for line in history.splitlines() if line and not line.startswith("#")]
        if csv_lines:
            try:
                rows = list(csv.DictReader(StringIO("\n".join(csv_lines))))
                if rows:
                    latest_volume = rows[-1].get("Volume")
            except (csv.Error, TypeError):
                latest_volume = None

    quote_point: dict = {}
    if quote_text:
        try:
            quote_point = json.loads(quote_text).get("quote", {})
        except (json.JSONDecodeError, TypeError):
            quote_point = {}
    quote = quote_point.get("value") if isinstance(quote_point, dict) else {}
    quote = quote if isinstance(quote, dict) else {}

    def display_volume(raw: str | None) -> str:
        try:
            value = float(str(raw))
        except (TypeError, ValueError):
            return "不可得"
        return f"{value:,.0f} 股（{value / 1e8:.2f} 亿股）"

    latest_five = stats.get("latest-5 average Volume (shares)")
    supplied_key = next(
        (key for key in stats if key.startswith("supplied-window average Volume")),
        None,
    )
    latest_twenty = stats.get("latest-20 average Volume (shares)")
    latest_twenty_unavailable = stats.get("latest-20 average Volume")
    observations = stats.get("ETF liquidity observations", "不可得")
    last_bar = stats.get("latest completed bar date", "不可得")
    five_dates = stats.get("latest-5 session dates", "不可得")
    supplied_average = stats.get(supplied_key) if supplied_key else None
    history_available = bool(
        history
        and "DATA_UNAVAILABLE" not in history
        and "[数据缺失:" not in history
    )
    source = "工具返回的 ETF OHLCV 数据" if history_available else "不可得"
    amount_missing = bool(history and "Amount (成交额) is unavailable" in history)

    lines = [
        "## ETF 流动性与交易分析",
        "",
        f"标的：{ticker}；分析日期：{trade_date}。本节由工具结果确定性渲染，不进行模型补算。",
        "",
        "### 行情与流动性事实",
        "",
        "| 项目 | 工具返回值 |",
        "| --- | --- |",
        f"| 实时/最新报价 | {quote.get('price', '不可得')} CNY |",
        f"| 昨收 | {quote.get('last_close', '不可得')} CNY |",
        f"| 报价涨跌幅 | {quote.get('change_pct', '不可得')}% |",
        f"| 快照换手率 | {quote.get('turnover_pct', '不可得')}% |",
        f"| 最新完整日线 | {last_bar} |",
        f"| 完整观测数 | {observations} |",
        f"| 最新完整日成交量 | {display_volume(latest_volume)} |",
        f"| 最近 5 个交易日 | {five_dates} |",
        f"| 最近 5 日均量 | {display_volume(latest_five)} |",
    ]
    if latest_twenty:
        lines.append(f"| 最近 20 日均量 | {display_volume(latest_twenty)} |")
    else:
        lines.append(
            f"| 最近 20 日均量 | 不可得：{latest_twenty_unavailable or '不足 20 个观测'} |"
        )
    if supplied_average:
        lines.append(f"| 当前工具窗口均量 | {display_volume(supplied_average)} |")

    lines.extend(
        [
            "",
            "### 解释与执行风险",
            "",
            f"- 日线来源：{source}；实时快照来源：{quote_point.get('source', 'Tencent Finance') if isinstance(quote_point, dict) else 'Tencent Finance'}。",
            "- 快照时间可能晚于最新完整日线，这是盘中快照与日终 K 线的正常时点差异，不据此推断休市。",
            "- Volume 的单位严格为股；快照 turnover_pct 是二级市场换手率，不是一级市场申购赎回金额。",
            (
                "- 日线历史工具不可用，因此成交量窗口和成交额均不可得，不作替代推算。"
                if not history_available
                else (
                    "- 成交额 Amount 不可得，因此不计算历史成交额均值，也不从市值或份额反推。"
                    if amount_missing
                    else "- 成交额以工具返回的 Amount 为准，不从成交量反推。"
                )
            ),
            "- 执行上应优先使用限价单，并结合实时买卖盘口控制大额订单的滑点；T+1 和涨跌幅限制会放大极端时点的退出摩擦。",
        ]
    )
    return "\n".join(lines)


def create_etf_liquidity_analyst(llm):
    """Analyze secondary-market liquidity without calling stock-flow tools."""
    del llm

    def node(state):
        ticker, trade_date = state["company_of_interest"], state["trade_date"]
        grounded_report = _render_grounded_liquidity_report(
            state["messages"], ticker, trade_date
        )
        if grounded_report is not None:
            return {
                "messages": [AIMessage(content=grounded_report)],
                "etf_liquidity_report": grounded_report,
            }
        lookback = get_config().get("market_lookback_days") or 30
        start_date = (
            date.fromisoformat(trade_date) - timedelta(days=lookback)
        ).isoformat()
        try:
            history = get_stock_data.func(ticker, start_date, trade_date)
        except VendorError as exc:
            history = f"# DATA_UNAVAILABLE: {exc}"
        try:
            quote = get_etf_quote.func(ticker, trade_date)
        except VendorError as exc:
            quote = json.dumps(
                {"quote": {"value": None, "status": "error", "notes": str(exc)}},
                ensure_ascii=False,
            )
        grounded_report = _render_grounded_liquidity_report(
            [
                ToolMessage(history, name="get_stock_data", tool_call_id="det-history"),
                ToolMessage(quote, name="get_etf_quote", tool_call_id="det-quote"),
            ],
            ticker,
            trade_date,
        )
        assert grounded_report is not None
        return {
            "messages": [AIMessage(content=grounded_report)],
            "etf_liquidity_report": grounded_report,
        }

    return node
