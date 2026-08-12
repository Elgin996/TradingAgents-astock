import re
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

# When a forbidden term appears within this many characters of one of these
# negation/exclusion markers, it is a compliant disclosure ("not applicable to
# this ETF") rather than a genuine stock-logic leak, and must not be flagged.
_NEGATION_MARKERS = (
    "不适用",
    "不涉及",
    "未使用",
    "无相关",
    "已排除",
    "不提供",
    "不比较",
    "禁止",
    "不是",
    "并非",
    "N/A",
)
_NEGATION_WINDOW = 12
ETF_IDENTITY_CONFLICT_TERMS = ("LOF",)

MIN_REPORT_LENGTH = 200

FAILURE_MARKERS = [
    "无法获取",
    "I cannot retrieve",
    "I don't have access",
    "unable to fetch",
    "工具调用失败",
]


def evaluate_market_data_quality(quality) -> dict[str, object]:
    """Convert a structured data-quality report into downstream gate fields."""
    if quality is None:
        return {"decision": None, "failed": False, "summary": ""}
    if hasattr(quality, "model_dump"):
        quality = quality.model_dump(mode="json")
    if not isinstance(quality, dict):
        return {"decision": "block", "failed": True, "summary": "市场数据质量对象无效"}
    decision = quality.get("decision", "block")
    grade = quality.get("grade", "F")
    flags = quality.get("flags") or []
    summary = f"市场数据质量：{grade} / {quality.get('source_status', 'UNKNOWN')}；决策：{decision}"
    if flags:
        summary += "；原因：" + "、".join(str(flag) for flag in flags)
    return {"decision": decision, "failed": decision == "block", "summary": summary}


def apply_market_data_quality_gate(state: dict) -> dict:
    """Small pure helper for callers that gate before report generation."""
    result = evaluate_market_data_quality(state.get("market_data_quality"))
    update = {
        "market_data_decision": result["decision"],
        "data_quality_failed": bool(result["failed"]),
    }
    if result["summary"]:
        update["data_quality_summary"] = result["summary"]
    if result["failed"]:
        update["technical_assessment"] = {
            "stance": "unavailable",
            "decision": "block",
        }
    return update


def _is_excluded_occurrence(report: str, pos: int, term: str) -> bool:
    """Recognize local negation and lists under an exclusion lead-in."""
    window = report[
        max(0, pos - _NEGATION_WINDOW): pos + len(term) + _NEGATION_WINDOW
    ]
    if any(marker in window for marker in _NEGATION_MARKERS):
        return True

    # Markdown bullets inherit a paragraph lead-in such as
    # "以下维度不提供：\n- 公司营收\n- 龙虎榜". Keep this broader check
    # inside the current paragraph so an unrelated negation cannot excuse a
    # later, genuine use of stock logic.
    block_start = report.rfind("\n\n", 0, pos) + 2
    block_end = report.find("\n\n", pos)
    if block_end == -1:
        block_end = len(report)
    block = report[block_start:block_end]
    first_line = block.splitlines()[0] if block else ""
    return any(marker in first_line for marker in _NEGATION_MARKERS)


def _find_unexcluded_hits(report: str, terms: tuple[str, ...]) -> list[str]:
    """Return terms with at least one use outside exclusion context."""
    hits: list[str] = []
    for term in terms:
        search_from = 0
        violated = False
        while True:
            pos = report.find(term, search_from)
            if pos == -1:
                break
            if not _is_excluded_occurrence(report, pos, term):
                violated = True
                break
            search_from = pos + len(term)
        if violated:
            hits.append(term)
    return hits


def find_forbidden_term_hits(report: str) -> list[str]:
    """Return ETF-forbidden terms genuinely used, not merely excluded."""
    return _find_unexcluded_hits(report, ETF_FORBIDDEN_TERMS)


def find_etf_identity_conflicts(report: str) -> list[str]:
    """Return incompatible product types asserted in an ETF report."""
    return _find_unexcluded_hits(report, ETF_IDENTITY_CONFLICT_TERMS)


def _etf_semantic_issues(analyst_type: str, report: str) -> tuple[list[str], bool]:
    """Return semantic issues and whether a critical source is absent."""
    issues: list[str] = []
    critical_missing = False
    if analyst_type == "market" and re.search(
        r"(?:跟踪)?指数.{0,60}(?:未能取得|无法(?:获取|量化)|无有效数据|数据缺失)",
        report,
        flags=re.DOTALL,
    ):
        issues.append("跟踪指数行情缺失")
        critical_missing = True
    if re.search(
        r"(?:数据状态|状态标记为).{0,12}[`*]*stale",
        report,
        flags=re.IGNORECASE,
    ):
        issues.append("使用过期披露数据")
    return issues, critical_missing


def _tracking_index_code(profile: object) -> str | None:
    """Read an optional code from flat or frozen InstrumentProfile shapes."""
    if not isinstance(profile, dict):
        return None
    raw = profile.get("tracking_index_code")
    if isinstance(raw, dict):
        value = raw.get("value")
        if isinstance(value, dict):
            raw = value.get("code")
        else:
            raw = value
    return str(raw) if raw else None


def _hard_check_report(
    analyst_type: str, report: str, analysis_mode: str = "stock"
) -> tuple:
    """Run hard checks on a single report. Returns (grade, detail, forbidden_hits)."""
    if not report or not report.strip():
        return ("F", "报告为空", [])

    length = len(report.strip())
    if analysis_mode == "etf":
        forbidden_hits = find_forbidden_term_hits(report)
        if forbidden_hits:
            name = ANALYST_NAMES.get(analyst_type, analyst_type)
            return (
                "F",
                f"{name}报告包含禁止的个股逻辑：{'、'.join(forbidden_hits)}",
                forbidden_hits,
            )
        identity_conflicts = find_etf_identity_conflicts(report)
        if identity_conflicts:
            name = ANALYST_NAMES.get(analyst_type, analyst_type)
            return (
                "F",
                f"{name}报告与冻结的 ETF 类型冲突：{'、'.join(identity_conflicts)}",
                [],
            )
    if length < MIN_REPORT_LENGTH:
        return ("D", f"报告过短 ({length} chars < {MIN_REPORT_LENGTH})", [])

    failure_count = sum(1 for m in FAILURE_MARKERS if m in report)
    stripped = report
    for m in FAILURE_MARKERS:
        stripped = stripped.replace(m, "")
    if failure_count > 0 and len(stripped.strip()) < MIN_REPORT_LENGTH:
        return ("D", f"报告主要由失败信息构成 ({failure_count} 处)", [])

    has_table = "|" in report and "---" in report
    missing_count = report.count("[数据缺失")

    issues = []
    if not has_table:
        issues.append("缺少汇总表格")
    if missing_count > 0:
        issues.append(f"{missing_count} 处数据缺失")
    semantic_issues: list[str] = []
    critical_missing = False
    if analysis_mode == "etf":
        semantic_issues, critical_missing = _etf_semantic_issues(
            analyst_type, report
        )
        issues.extend(semantic_issues)

    if critical_missing or missing_count >= 3:
        return ("C", "；".join(issues), [])
    if not has_table or missing_count > 0 or semantic_issues:
        return ("B", "；".join(issues) if issues else "基本合格", [])

    return ("A", f"完整 ({length} chars)", [])


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
        unavailable = dict(state.get("analysis_unavailable_capabilities", {}))
        market_quality_result = evaluate_market_data_quality(state.get("market_data_quality"))
        evidence_validation = None
        capabilities = state.get("analysis_capabilities")
        missing_tracking_code = analysis_mode == "etf" and not _tracking_index_code(
            state.get("instrument_profile")
        )
        if missing_tracking_code:
            unavailable.setdefault(
                "tracking_index_price_history",
                "未提供跟踪指数代码；本次仅分析 ETF 自身行情。",
            )

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

        evidence_bundle = state.get("technical_evidence_bundle")
        if evidence_bundle and reports.get("market_report"):
            try:
                from tradingagents.technical.evidence import TechnicalEvidenceBundle
                from tradingagents.technical.report_validation import validate_report

                if not isinstance(evidence_bundle, TechnicalEvidenceBundle):
                    evidence_bundle = TechnicalEvidenceBundle.model_validate(evidence_bundle)
                evidence_validation = validate_report(reports["market_report"], evidence_bundle)
            except Exception as exc:
                evidence_validation = {"valid": False, "issues": [f"validator_error:{type(exc).__name__}"]}
        evidence_failed = bool(evidence_validation is not None and not (
            evidence_validation.valid if hasattr(evidence_validation, "valid") else evidence_validation.get("valid", False)
        ))

        hard_results = {}
        forbidden_hits_by_analyst: dict[str, list[str]] = {}
        identity_conflicts_by_analyst: dict[str, list[str]] = {}
        for analyst_type, field in fields.items():
            grade, detail, forbidden_hits = _hard_check_report(
                analyst_type, reports[field], analysis_mode
            )
            hard_results[analyst_type] = (grade, detail)
            if forbidden_hits:
                forbidden_hits_by_analyst[analyst_type] = forbidden_hits
            if analysis_mode == "etf":
                identity_conflicts = find_etf_identity_conflicts(reports[field])
                if identity_conflicts:
                    identity_conflicts_by_analyst[analyst_type] = identity_conflicts
        if missing_tracking_code and "market" in hard_results:
            grade, detail = hard_results["market"]
            if grade not in ("F", "D"):
                hard_results["market"] = (
                    "C",
                    f"{detail}；未提供跟踪指数代码，指数行情对比不可用",
                )

        hard_summary_lines = []
        for analyst_type, (grade, detail) in hard_results.items():
            name = ANALYST_NAMES[analyst_type]
            hard_summary_lines.append(f"- {name}: [{grade}] {detail}")
        hard_summary = "\n".join(hard_summary_lines) if hard_summary_lines else "- （无启用分析师栏目）"

        fail_count = sum(
            1 for _, (g, _) in hard_results.items() if g in ("F", "D")
        )
        forbidden_term_hit = bool(forbidden_hits_by_analyst)
        identity_conflict_hit = bool(identity_conflicts_by_analyst)
        # A genuine forbidden-term leak (individual-stock logic in an ETF
        # report) is a standalone blocking signal — it must not need to wait
        # for enough *other* reports to also fail before the run is blocked.
        report_quality_failed = bool(fields) and (
            fail_count >= threshold or forbidden_term_hit or identity_conflict_hit
        )
        data_quality_failed = (
            report_quality_failed
            or bool(market_quality_result["failed"])
            or evidence_failed
        )

        llm_review = ""
        if fields and not data_quality_failed:
            try:
                review_prompt = _build_review_prompt(
                    reports, trade_date, ticker, fields
                )
                response = llm.invoke(review_prompt)
                llm_review = response.content
            except Exception as e:
                llm_review = f"（LLM 复审失败: {type(e).__name__}: {e}）"

        verdict = "未通过 ❌" if data_quality_failed else "通过 ✅"
        verdict_reason = f"{fail_count} 项硬检查未达标，阈值为 {threshold} 项。"
        if forbidden_term_hit:
            verdict_reason += " 检测到禁用词命中，独立阻断（不受阈值影响）。"
        if identity_conflict_hit:
            verdict_reason += " 检测到证券类型冲突，独立阻断（不受阈值影响）。"
        if market_quality_result["failed"]:
            verdict_reason += " 市场数据质量决策为阻断。"
        if evidence_failed:
            verdict_reason += " 技术报告事实核验失败。"
        summary = (
            f"## 数据质量门控结果\n\n"
            f"**标的**: {ticker} | **交易日**: {trade_date}\n\n"
            f"### 硬检查结果\n{hard_summary}\n\n"
            f"### LLM 复审\n"
            f"{llm_review if llm_review else '（跳过 — 硬检查触发阻断）'}\n\n"
            f"### 门控判定\n"
            f"**{verdict}** — {verdict_reason}\n"
        )
        if market_quality_result["summary"]:
            summary += f"\n### 市场数据门控\n{market_quality_result['summary']}\n"
        if evidence_validation is not None:
            validation_payload = (
                evidence_validation.model_dump(mode="json")
                if hasattr(evidence_validation, "model_dump")
                else evidence_validation
            )
            summary += "\n### 技术报告事实核验\n"
            summary += "通过 ✅" if validation_payload.get("valid") else "失败 ❌：" + "、".join(validation_payload.get("issues", []))
            summary += "\n"
        if forbidden_hits_by_analyst:
            summary += "\n### 禁用词命中\n" + "\n".join(
                f"- {ANALYST_NAMES.get(analyst_type, analyst_type)}: {'、'.join(hits)}"
                for analyst_type, hits in forbidden_hits_by_analyst.items()
            ) + "\n"
        if identity_conflicts_by_analyst:
            summary += "\n### 证券类型冲突\n" + "\n".join(
                f"- {ANALYST_NAMES.get(analyst_type, analyst_type)}: {'、'.join(hits)}"
                for analyst_type, hits in identity_conflicts_by_analyst.items()
            ) + "\n"
        if unavailable:
            summary += "\n### 不可得数据\n" + "\n".join(
                f"- {capability}: {reason}"
                for capability, reason in unavailable.items()
            ) + "\n"

        return {
            "data_quality_summary": summary,
            "data_quality_failed": data_quality_failed,
            "market_data_decision": market_quality_result["decision"],
            "technical_report_validation": (
                evidence_validation.model_dump(mode="json")
                if hasattr(evidence_validation, "model_dump")
                else evidence_validation
            ),
        }

    return quality_gate_node
