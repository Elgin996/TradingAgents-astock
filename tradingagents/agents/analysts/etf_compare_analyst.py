import json

from langchain_core.messages import AIMessage, ToolMessage

from tradingagents.agents.utils.agent_utils import (
    get_etf_peer_comparison,
    get_etf_structure_alerts,
)
from tradingagents.dataflows.vendors.base import VendorError


def _comparison_tool_payloads(messages) -> dict[str, str]:
    return {
        str(message.name or ""): str(message.content or "")
        for message in messages
        if isinstance(message, ToolMessage)
    }


def _render_grounded_comparison_report(messages, ticker: str, trade_date: str) -> str | None:
    """Render peer rows and alerts directly from the two audited tool payloads."""
    payloads = _comparison_tool_payloads(messages)
    peer_text = payloads.get("get_etf_peer_comparison")
    alert_text = payloads.get("get_etf_structure_alerts")
    if not peer_text and not alert_text:
        return None

    def point(text: str | None, key: str) -> dict:
        if not text:
            return {}
        try:
            value = json.loads(text).get(key, {})
        except (json.JSONDecodeError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    peer_point = point(peer_text, "peer_comparison")
    peer_value = peer_point.get("value")
    peer_value = peer_value if isinstance(peer_value, dict) else {}
    peers = peer_value.get("peers")
    peers = [row for row in peers if isinstance(row, dict)] if isinstance(peers, list) else []
    alert_point = point(alert_text, "structure_alerts")
    alert_value = alert_point.get("value")
    alert_value = alert_value if isinstance(alert_value, dict) else {}
    alerts = alert_value.get("alerts")
    alerts = [row for row in alerts if isinstance(row, dict)] if isinstance(alerts, list) else []

    lines = [
        "## ETF 同类比较与结构预警",
        "",
        f"标的：{ticker}；分析日期：{trade_date}。本节仅渲染工具返回字段，不补造同类代码、排名或告警。",
        "",
        "### 同跟踪指数 ETF",
        "",
        f"跟踪指数：{peer_value.get('tracking_index_name', '不可得')}；工具状态：{peer_point.get('status', '不可得')}。",
        "",
        "| 代码 | 名称 | 管理费 | 托管费 | 披露份额（亿份） | AUM（亿元） | 快照换手率（%） | 流通市值（亿元） | 披露期 | 状态 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if peers:
        for row in peers:
            lines.append(
                "| {symbol} | {name} | {management} | {custodian} | {shares} | "
                "{aum} | {turnover} | {mcap} | {as_of} | {status} |".format(
                    symbol=row.get("symbol", "不可得"),
                    name=row.get("fund_name", "不可得"),
                    management=row.get("management_fee", "不可得"),
                    custodian=row.get("custodian_fee", "不可得"),
                    shares=row.get("shares_yi", "不可得"),
                    aum=row.get("aum_yi", "不可得"),
                    turnover=row.get("turnover_pct", "不可得"),
                    mcap=row.get("float_mcap_yi", "不可得"),
                    as_of=row.get("shares_as_of", "不可得"),
                    status=row.get("status", "不可得"),
                )
            )
    else:
        lines.append("| — | — | — | — | — | — | — | — | — | 无可比数据 |")

    ok_peer_count = sum(1 for row in peers if row.get("status") == "ok")
    lines.extend(
        [
            "",
            (
                "仅取得主体自身，不能形成同类排名。"
                if ok_peer_count < 2
                else f"取得 {ok_peer_count} 个可用产品；表格保留工具原始字段，未自行合成排名。"
            ),
            "",
            "### 确定性结构预警",
            "",
            "| 规则 | 严重度 | 截止日 | 数值 | 单位 | 信息 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    alert_status = str(alert_point.get("status") or "不可得")
    if alerts:
        for row in alerts:
            lines.append(
                f"| {row.get('rule', '不可得')} | {row.get('severity', '不可得')} | "
                f"{row.get('as_of', '不可得')} | {row.get('value', '不可得')} | "
                f"{row.get('unit', '不可得')} | {row.get('message', '不可得')} |"
            )
    elif alert_status in {"error", "missing", "unsupported", "不可得"}:
        lines.append("| 不可得 | — | — | — | — | 结构预警工具不可用或未返回有效数据 |")
    else:
        lines.append("| 无 | — | — | — | — | 工具未返回触发的结构预警 |")

    excluded = peer_value.get("excluded_fields") or []
    excluded_rules = alert_value.get("excluded_rules") or []
    lines.extend(
        [
            "",
            "### 口径与限制",
            "",
            f"- 同类数据来源：{peer_point.get('source', '不可得')}；as_of：{peer_point.get('as_of', '不可得')}。",
            f"- 预警数据来源：{alert_point.get('source', '不可得')}；as_of：{alert_point.get('as_of', '不可得')}。",
            f"- 明确排除的比较字段：{', '.join(map(str, excluded)) if excluded else '无'}。",
            f"- 明确关闭的预警规则：{', '.join(map(str, excluded_rules)) if excluded_rules else '无'}。",
            "- 披露份额/AUM 不是实时净申赎；换手率与流通市值直接保留腾讯快照口径，不从份额推算。",
        ]
    )
    return "\n".join(lines)


def create_etf_compare_analyst(llm):
    """Compare same-index ETFs and emit Stage-3 rule alerts without closed metrics."""
    del llm

    def node(state):
        ticker, trade_date = state["company_of_interest"], state["trade_date"]
        grounded_report = _render_grounded_comparison_report(
            state["messages"], ticker, trade_date
        )
        if grounded_report is not None:
            return {
                "messages": [AIMessage(content=grounded_report)],
                "etf_compare_report": grounded_report,
            }
        try:
            peers = get_etf_peer_comparison.func(ticker, trade_date)
        except VendorError as exc:
            peers = json.dumps(
                {"peer_comparison": {"value": None, "status": "error", "notes": str(exc)}},
                ensure_ascii=False,
            )
        try:
            alerts = get_etf_structure_alerts.func(ticker, trade_date)
        except VendorError as exc:
            alerts = json.dumps(
                {"structure_alerts": {"value": None, "status": "error", "notes": str(exc)}},
                ensure_ascii=False,
            )
        grounded_report = _render_grounded_comparison_report(
            [
                ToolMessage(peers, name="get_etf_peer_comparison", tool_call_id="det-peers"),
                ToolMessage(alerts, name="get_etf_structure_alerts", tool_call_id="det-alerts"),
            ],
            ticker,
            trade_date,
        )
        assert grounded_report is not None
        return {
            "messages": [AIMessage(content=grounded_report)],
            "etf_compare_report": grounded_report,
        }

    return node
