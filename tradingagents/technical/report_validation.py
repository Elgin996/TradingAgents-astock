"""Conservative post-generation checks for evidence-grounded reports."""

from __future__ import annotations

import re
from datetime import date

from tradingagents.dataflows.models import ReportValidationResult
from .evidence import TechnicalEvidenceBundle


_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER = re.compile(r"(?<![A-Za-z])(?<!\d)(?:\d+(?:\.\d+)?)(?:%|\b)")
_EXECUTIVE_TERMS = ("买入", "卖出", "强烈看多", "强烈看空", "buy", "sell")
PRODUCT_PROHIBITED_TERMS = (
    "折溢价",
    "折价",
    "溢价",
    "跟踪误差",
    "跟踪差异",
    "套利机会",
    "资金净流入",
    "实际持仓变化",
)
_PRODUCT_NEGATION_CONTEXT = (
    "不",
    "无",
    "未取得",
    "未提供",
    "不可得",
    "不可用",
    "不能",
    "禁止",
    "不输出",
    "数据不足",
    "关闭",
)


def _numeric_facts(bundle: TechnicalEvidenceBundle) -> set[float]:
    values: set[float] = set()

    def collect(value, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                collect(child, str(child_key))
        elif isinstance(value, (list, tuple, set)):
            for child in value:
                collect(child, key)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            values.add(round(float(value), 8))
        elif isinstance(value, str) and key not in {"symbol", "source", "signal_id", "explanation_key"}:
            try:
                values.add(round(float(value), 8))
            except ValueError:
                pass

    collect(bundle.model_dump(mode="json"))
    return values


def validate_report(report: str, bundle: TechnicalEvidenceBundle) -> ReportValidationResult:
    issues: list[str] = []
    cited: list[str] = []
    if not report or not report.strip():
        return ReportValidationResult(valid=False, issues=["empty_report"])
    if bundle.data_quality_decision == "block":
        stance = bundle.assessment.stance if bundle.assessment else "unavailable"
        if stance not in {None, "unavailable"} and any(term in report.lower() for term in ("看多", "看空", "bullish", "bearish")):
            issues.append("blocked_data_has_directional_conclusion")
    if bundle.data_quality_decision == "observe_only":
        for term in _EXECUTIVE_TERMS:
            if term.lower() in report.lower():
                issues.append(f"observe_only_executive_term:{term}")
    for raw_date in _DATE.findall(report):
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError:
            issues.append(f"invalid_date:{raw_date}")
            continue
        if parsed < bundle.analysis_start or parsed > bundle.analysis_end:
            # Dates in a report must be in the frozen analysis interval unless
            # the report explicitly quotes a version/snapshot date.
            issues.append(f"date_outside_evidence:{raw_date}")
    allowed = _numeric_facts(bundle)
    # Dates are checked above as dates; their components must not be treated as
    # independent unsupported numeric facts.
    numeric_text = _DATE.sub(" ", report)
    # Indicator and signal identifiers contain periods/parameters (e.g.
    # ``close_sma_20`` and ``rolling_breakout20``). They are labels, not facts.
    # Inline-code blocks are already evidence identifiers/values and are not
    # independently parsed here; their values are covered by the bundle.
    numeric_text = re.sub(r"`[^`]*`", " ", numeric_text)
    numeric_text = re.sub(r"[A-Za-z_][A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*", " ", numeric_text)
    for token in _NUMBER.findall(numeric_text):
        number = token.rstrip("%").strip()
        try:
            value = round(float(number), 8)
        except ValueError:
            continue
        if value == 0 or value == 1:
            continue
        if value not in allowed:
            issues.append(f"numeric_fact_not_in_evidence:{token}")
    if bundle.snapshot_id and bundle.snapshot_id not in report:
        issues.append("missing_snapshot_id")
    if bundle.data_quality_grade in {"C", "D", "F"} and not any(word in report for word in ("数据质量", "降级", "不可", "缺失", "stale", "冲突")):
        issues.append("missing_quality_disclosure")
    return ReportValidationResult(valid=not issues, issues=list(dict.fromkeys(issues)), cited_evidence_ids=cited)


def validate_evidence_report(report: str, bundle: TechnicalEvidenceBundle) -> ReportValidationResult:
    return validate_report(report, bundle)


def find_prohibited_product_terms(report: str) -> list[str]:
    """Find unsupported ETF terminology while allowing explicit negation."""

    found: list[str] = []
    for term in PRODUCT_PROHIBITED_TERMS:
        start = 0
        while True:
            index = report.find(term, start)
            if index < 0:
                break
            context = report[max(0, index - 14):index]
            if not any(marker in context for marker in _PRODUCT_NEGATION_CONTEXT):
                found.append(term)
            start = index + len(term)
    return list(dict.fromkeys(found))


def validate_product_report(report: str, bundle) -> ReportValidationResult:
    """Validate a product evidence report without imposing legacy stock fields."""

    issues: list[str] = []
    if not report or not report.strip():
        return ReportValidationResult(valid=False, issues=["empty_report"])
    for term in find_prohibited_product_terms(report):
        issues.append(f"prohibited_product_term:{term}")
    snapshot_id = getattr(bundle, "bundle_snapshot_id", "")
    if snapshot_id and snapshot_id not in report:
        issues.append("missing_bundle_snapshot_id")
    subject_quality = getattr(bundle, "subject_quality", None)
    if subject_quality is not None and subject_quality.grade in {"C", "D", "F"}:
        if not any(word in report for word in ("数据质量", "降级", "不可", "缺失", "observe_only", "block")):
            issues.append("missing_quality_disclosure")
    assessment = getattr(bundle, "product_assessment", {}) or {}
    state = assessment.get("product_state") if isinstance(assessment, dict) else ""
    if state == "conflicted" and any(term in report.lower() for term in ("强烈看多", "强烈看空", "strongly bullish", "strongly bearish")):
        issues.append("conflicted_data_has_strong_direction")
    return ReportValidationResult(valid=not issues, issues=list(dict.fromkeys(issues)))
