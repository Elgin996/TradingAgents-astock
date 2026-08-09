from typing import Optional

REPORT_FIELDS = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
    "policy": "policy_report",
    "hot_money": "hot_money_report",
    "lockup": "lockup_report",
}

ANALYST_NAMES = {
    "market": "技术分析师",
    "social": "情绪分析师",
    "news": "新闻分析师",
    "fundamentals": "基本面分析师",
    "policy": "政策分析师",
    "hot_money": "游资追踪师",
    "lockup": "解禁监控师",
    "etf_liquidity": "ETF流动性分析师",
    "etf_structure": "ETF结构分析师",
    "etf_index_news": "指数新闻与政策分析师",
    "etf_compare": "ETF比较与预警分析师",
}
ETF_REPORT_FIELDS = {
    "market": "market_report",
    "etf_liquidity": "etf_liquidity_report",
    "etf_structure": "etf_profile_report",
    "etf_index_news": "etf_index_news_report",
    "etf_compare": "etf_compare_report",
}
ETF_FORBIDDEN_TERMS = ("公司营收", "净利润", "董监高", "解禁", "限售", "龙虎榜")

MIN_REPORT_LENGTH = 200

FAILURE_MARKERS = [
    "无法获取",
    "I cannot retrieve",
    "I don't have access",
    "unable to fetch",
    "工具调用失败",
]


def _hard_check_report(
    analyst_type: str, report: str, analysis_mode: str = "stock"
) -> tuple:
    """Run hard checks on a single report. Returns (grade, detail)."""
    if not report or not report.strip():
        return ("F", "报告为空")

    length = len(report.strip())
    if analysis_mode == "etf" and any(term in report for term in ETF_FORBIDDEN_TERMS):
        return ("F", "ETF 报告包含禁止的个股逻辑")
    if length < MIN_REPORT_LENGTH:
        return ("D", f"报告过短 ({length} chars < {MIN_REPORT_LENGTH})")

    failure_count = sum(1 for m in FAILURE_MARKERS if m in report)
    stripped = report
    for m in FAILURE_MARKERS:
        stripped = stripped.replace(m, "")
    if failure_count > 0 and len(stripped.strip()) < MIN_REPORT_LENGTH:
        return ("D", f"报告主要由失败信息构成 ({failure_count} 处)")

    has_table = "|" in report and "---" in report
    missing_count = report.count("[数据缺失")

    issues = []
    if not has_table:
        issues.append("缺少汇总表格")
    if missing_count > 0:
        issues.append(f"{missing_count} 处数据缺失")

    if missing_count >= 3:
        return ("C", "；".join(issues))
    if not has_table or missing_count > 0:
        return ("B", "；".join(issues) if issues else "基本合格")

    return ("A", f"完整 ({length} chars)")


def _fail_threshold(n_fields: int) -> int:
    """Scaled skip/block threshold for the number of analysts actually graded."""
    return max(2, n_fields // 2 + 1)


def _build_review_prompt(
    reports: dict,
    trade_date: str,
    ticker: str,
    fields: Optional[dict] = None,
) -> str:
    """Build the LLM review prompt for the selected analyst set."""
    from tradingagents.agents.utils.structured import strip_freetext_marker

    fields = fields if fields is not None else REPORT_FIELDS
    report_sections = []
    for analyst_type, field in fields.items():
        name = ANALYST_NAMES[analyst_type]
        content = reports.get(field, "（未运行）")
        if not content:
            content = "（报告为空）"
        else:
            content = strip_freetext_marker(content)
        if len(content) > 3000:
            content = content[:3000] + "\n... (truncated for review)"
        report_sections.append(f"### {name} ({analyst_type})\n{content}")

    all_reports = "\n\n".join(report_sections)
    n = len(fields)

    return f"""你是数据质量审核员。以下是 {n} 位分析师对 {ticker} 在 {trade_date} 的研究报告。请逐一审核。

{all_reports}

---

请按以下格式输出审核结果（不要输出其他内容）：

## 数据质量审核报告

**标的**: {ticker} | **日期**: {trade_date}

| 分析师 | 评级 | 数据时效 | 缺失项 | 备注 |
|--------|------|----------|--------|------|
（仅列出上方实际运行的分析师）

**整体评级**: A/B/C/D/F
**数据可信度**: 高/中/低
**建议**: （如有数据缺失，提醒辩论阶段谨慎使用该报告）

评级标准：
- A: 必采清单全部覆盖，数据时效匹配，有汇总表格
- B: 缺少 1-2 项非关键数据，整体可用
- C: 缺少 3+ 项或有数据时效问题，需谨慎使用
- D: 大量缺失或主要为失败信息，可信度低
- F: 报告为空或完全无效
"""


def create_quality_gate(llm, selected_analysts=None, analysis_mode: str = "stock"):
    """Factory for the data quality gate node.

    Sits between the last analyst Msg Clear and Bull Researcher.
    Layer 1: hard checks (code). Layer 2: LLM review (one call).
    Only grades analysts that were selected for the run.
    Writes data_quality_summary and data_quality_failed to state.
    """
    source_fields = ETF_REPORT_FIELDS if analysis_mode == "etf" else REPORT_FIELDS
    base_fields = {
        k: v
        for k, v in source_fields.items()
        if selected_analysts is None or k in selected_analysts
    }

    def quality_gate_node(state) -> dict:
        trade_date = state["trade_date"]
        ticker = state["company_of_interest"]
        unavailable = state.get("analysis_unavailable_capabilities", {})
        capabilities = state.get("analysis_capabilities")

        fields = dict(base_fields)
        if analysis_mode == "etf" and capabilities is not None:
            from tradingagents.dataflows.analysis_capabilities import (
                ETF_ANALYST_REQUIRED_CAPABILITIES,
            )

            enabled = frozenset(capabilities)
            fields = {
                analyst: field
                for analyst, field in base_fields.items()
                if ETF_ANALYST_REQUIRED_CAPABILITIES.get(
                    analyst, frozenset()
                ).issubset(enabled)
            }
        threshold = _fail_threshold(len(fields)) if fields else 2

        reports = {}
        for analyst_type, field in fields.items():
            reports[field] = state.get(field, "")

        hard_results = {}
        for analyst_type, field in fields.items():
            grade, detail = _hard_check_report(
                analyst_type, reports[field], analysis_mode
            )
            hard_results[analyst_type] = (grade, detail)

        hard_summary_lines = []
        for analyst_type, (grade, detail) in hard_results.items():
            name = ANALYST_NAMES[analyst_type]
            hard_summary_lines.append(f"- {name}: [{grade}] {detail}")
        hard_summary = "\n".join(hard_summary_lines) if hard_summary_lines else "- （无启用分析师栏目）"

        fail_count = sum(
            1 for _, (g, _) in hard_results.items() if g in ("F", "D")
        )
        data_quality_failed = bool(fields) and fail_count >= threshold

        llm_review = ""
        if fields and fail_count < threshold:
            try:
                review_prompt = _build_review_prompt(
                    reports, trade_date, ticker, fields
                )
                response = llm.invoke(review_prompt)
                llm_review = response.content
            except Exception as e:
                llm_review = f"（LLM 复审失败: {type(e).__name__}: {e}）"

        verdict = "未通过 ❌" if data_quality_failed else "通过 ✅"
        summary = (
            f"## 数据质量门控结果\n\n"
            f"**标的**: {ticker} | **交易日**: {trade_date}\n\n"
            f"### 硬检查结果\n{hard_summary}\n\n"
            f"### LLM 复审\n"
            f"{llm_review if llm_review else '（跳过 — 多数报告未通过硬检查）'}\n\n"
            f"### 门控判定\n"
            f"**{verdict}** — {fail_count} 项硬检查未达标，阈值为 {threshold} 项。\n"
        )
        if unavailable:
            summary += "\n### 不可得数据\n" + "\n".join(
                f"- {capability}: {reason}"
                for capability, reason in unavailable.items()
            ) + "\n"

        return {
            "data_quality_summary": summary,
            "data_quality_failed": data_quality_failed,
        }

    return quality_gate_node
