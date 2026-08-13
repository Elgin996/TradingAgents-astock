import json
from datetime import date, timedelta

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_utils import (
    get_etf_announcements,
    get_global_news,
    get_news,
)
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.vendors.base import VendorError


def _news_payload_status(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized or any(
        marker in normalized
        for marker in ("[数据缺失:", "DATA_UNAVAILABLE", "工具调用失败")
    ):
        return "不可得"
    if "No news found" in normalized:
        return "无命中"
    return "可用"


def _render_grounded_index_news_report(
    *,
    ticker: str,
    index_code: str,
    trade_date: str,
    start_date: str,
    index_news: str,
    global_news: str,
    announcements_text: str,
) -> str:
    """Combine exact dated source payloads without model-generated events."""
    try:
        point = json.loads(announcements_text).get("announcements", {})
    except (json.JSONDecodeError, TypeError):
        point = {}
    announcements = point.get("value") if isinstance(point, dict) else []
    announcements = (
        [item for item in announcements if isinstance(item, dict)]
        if isinstance(announcements, list)
        else []
    )
    index_status = _news_payload_status(index_news)
    global_status = _news_payload_status(global_news)
    announcement_status = point.get("status", "不可得") if isinstance(point, dict) else "不可得"
    lines = [
        "## 跟踪指数新闻、政策与基金公告",
        "",
        f"ETF：{ticker}；跟踪指数：{index_code}；证据窗口：{start_date} 至 {trade_date}。",
        "本节直接呈现允许工具的返回内容，不生成工具未返回的事件、资金流或政策结论。",
        "",
        "| 证据源 | 状态 | 截止日 | 使用口径 |",
        "| --- | --- | --- | --- |",
        f"| 跟踪指数新闻 | {index_status} | {trade_date} | 仅代码 {index_code} 的日期过滤结果 |",
        f"| 宏观/全球新闻 | {global_status} | {trade_date} | 仅作背景，不自动归因到指数 |",
        f"| ETF 公告 | {announcement_status} | {trade_date} | 仅公告发布日期不晚于分析日的记录 |",
        "",
        "### 跟踪指数新闻原始摘要",
        "",
        index_news.strip() or "[数据缺失: 跟踪指数新闻]",
        "",
        "### 基金公告",
        "",
        "| 发布日期 | 标题 |",
        "| --- | --- |",
    ]
    if announcements:
        for item in announcements:
            published = str(
                item.get("NOTICE_DATE")
                or item.get("NoticeDate")
                or item.get("PUBLISHDATE")
                or item.get("PUBLISHDATEDesc")
                or "不可得"
            )[:10]
            title = str(
                item.get("TITLE")
                or item.get("NoticeTitle")
                or item.get("NOTICETITLE")
                or "未提供标题"
            ).replace("|", "｜")
            lines.append(f"| {published} | {title} |")
    else:
        lines.append("| — | 工具未返回符合日期条件的公告 |")
    lines.extend(
        [
            "",
            "### 宏观背景原始摘要",
            "",
            global_news.strip() or "[数据缺失: 宏观/全球新闻]",
            "",
            "### 使用限制",
            "",
            "- 单一成分股新闻不自动上升为指数结论；只有源文本明确关联指数/行业时才作为背景。",
            "- 基金公告的运营、系统或人员事项不自动解释为跟踪表现变化。",
            "- 本节不使用公司财务、限售解禁或个人交易信息。",
        ]
    )
    return "\n".join(lines)


def create_etf_index_news_analyst(llm):
    """Review index/policy context and dated fund announcements."""
    del llm

    def node(state):
        ticker, trade_date = state["company_of_interest"], state["trade_date"]
        profile = state.get("instrument_profile") or {}
        reference = profile.get("reference_instrument") or {}
        index_code = str(reference.get("code") or "").strip()
        lookback = get_config().get("market_lookback_days") or 30
        start_date = (
            date.fromisoformat(trade_date) - timedelta(days=lookback)
        ).isoformat()
        try:
            index_news = get_news.func(index_code, start_date, trade_date)
        except VendorError as exc:
            index_news = f"[数据缺失: 跟踪指数新闻] {exc}"
        try:
            global_news = get_global_news.func(trade_date, lookback, 5)
        except VendorError as exc:
            global_news = f"[数据缺失: 宏观/全球新闻] {exc}"
        try:
            announcements = get_etf_announcements.func(ticker, trade_date)
        except VendorError as exc:
            announcements = json.dumps(
                {"announcements": {"value": None, "status": "error", "notes": str(exc)}},
                ensure_ascii=False,
            )
        report = _render_grounded_index_news_report(
            ticker=ticker,
            index_code=index_code,
            trade_date=trade_date,
            start_date=start_date,
            index_news=index_news,
            global_news=global_news,
            announcements_text=announcements,
        )
        return {
            "messages": [AIMessage(content=report)],
            "etf_index_news_report": report,
        }

    return node
