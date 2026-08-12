"""Evidence package and report renderer for product-aware technical analysis."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.dataflows.analysis_bundle import AnalysisMarketDataBundle
from tradingagents.dataflows.models import (
    DataQualityReport,
    IndicatorValue,
    RelativeMetric,
    SeriesAlignmentReport,
    TechnicalSignal,
)
from .products import (
    ProductSignalEvaluation,
    assess_product,
    calculate_product_indicator_frame,
    evaluate_product_signals,
    infer_liquidity_state,
    indicator_values_from_product_frame,
)
from .relative import calculate_relative_metrics, technical_state_consistency


class ProductTechnicalEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_product: str
    instrument_profile: dict[str, Any] = Field(default_factory=dict)
    subject_quality: DataQualityReport
    reference_quality: DataQualityReport | None = None
    alignment: SeriesAlignmentReport | None = None
    subject_indicators: list[IndicatorValue] = Field(default_factory=list)
    reference_indicators: list[IndicatorValue] = Field(default_factory=list)
    subject_signals: list[TechnicalSignal] = Field(default_factory=list)
    reference_signals: list[TechnicalSignal] = Field(default_factory=list)
    relative_metrics: list[RelativeMetric] = Field(default_factory=list)
    product_assessment: dict[str, Any] = Field(default_factory=dict)
    unavailable_capabilities: dict[str, str] = Field(default_factory=dict)
    bundle_snapshot_id: str
    versions: dict[str, str] = Field(default_factory=dict)

    def to_prompt(self) -> str:
        import json

        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )


def _latest_indicator_values(frame) -> list[IndicatorValue]:
    if frame is None or frame.empty:
        return []
    latest = frame.iloc[-1]
    observed = frame["trade_date"].iloc[-1]
    observed_date = observed.date() if hasattr(observed, "date") else observed
    values: list[IndicatorValue] = []
    ignored = {"trade_date", "open", "high", "low", "close", "volume", "amount"}
    for name, value in latest.items():
        if name in ignored:
            continue
        numeric = None if value is None else value
        try:
            if numeric != numeric:
                numeric = None
            else:
                numeric = float(numeric)
        except (TypeError, ValueError):
            numeric = None
        values.append(
            IndicatorValue(
                name=name,
                value=numeric,
                trade_date=observed_date,
                parameters={},
                warmup_complete=numeric is not None,
                engine_version="product-technical-rules-v2",
            )
        )
    return values


def _evaluation_for_bundle(
    bundle: AnalysisMarketDataBundle,
    *,
    subject_evaluation: ProductSignalEvaluation | None,
    reference_evaluation: ProductSignalEvaluation | None,
) -> tuple[ProductSignalEvaluation | None, ProductSignalEvaluation | None]:
    if subject_evaluation is None and bundle.subject.bars and bundle.subject.quality.decision != "block":
        subject_evaluation = evaluate_product_signals(
            bundle.subject.bars,
            bundle.analysis_product,
            quality_grade=bundle.subject.quality.grade,
            snapshot_id=bundle.subject.snapshot_id or "",
        )
    if reference_evaluation is None and bundle.reference and bundle.reference.bars and bundle.reference.quality.decision != "block":
        reference_evaluation = evaluate_product_signals(
            bundle.reference.bars,
            "index" if bundle.reference.request.instrument_type == "index" else "a_share_stock",
            quality_grade=bundle.reference.quality.grade,
            snapshot_id=bundle.reference.snapshot_id or "",
        )
    return subject_evaluation, reference_evaluation


def build_product_evidence_bundle(
    bundle: AnalysisMarketDataBundle,
    *,
    subject_evaluation: ProductSignalEvaluation | None = None,
    reference_evaluation: ProductSignalEvaluation | None = None,
    product_assessment: Any | None = None,
    unavailable_capabilities: dict[str, str] | None = None,
) -> ProductTechnicalEvidenceBundle:
    subject_evaluation, reference_evaluation = _evaluation_for_bundle(
        bundle,
        subject_evaluation=subject_evaluation,
        reference_evaluation=reference_evaluation,
    )
    if product_assessment is None:
        liquidity_state = infer_liquidity_state(
            subject_evaluation.frame if subject_evaluation else None,
            bundle.analysis_product,
        )
        product_assessment = assess_product(
            bundle.analysis_product,
            subject_evaluation.assessment if subject_evaluation else None,
            reference_assessment=reference_evaluation.assessment if reference_evaluation else None,
            alignment=bundle.alignment,
            relative_metrics=(
                calculate_relative_metrics(
                    bundle.subject,
                    bundle.reference,
                    alignment=bundle.alignment,
                )
                if bundle.reference is not None
                else []
            ),
            liquidity_state=liquidity_state,
        )
    relative_metrics = (
        calculate_relative_metrics(
            bundle.subject,
            bundle.reference,
            alignment=bundle.alignment,
        )
        if bundle.reference is not None
        else []
    )
    if bundle.reference is not None:
        relative_metrics.append(
            technical_state_consistency(
                subject_evaluation.assessment if subject_evaluation else None,
                reference_evaluation.assessment if reference_evaluation else None,
                bundle=bundle,
            )
        )
    if hasattr(product_assessment, "model_dump"):
        assessment_payload = product_assessment.model_dump(mode="json")
    else:
        assessment_payload = dict(product_assessment or {})
    return ProductTechnicalEvidenceBundle(
        analysis_product=bundle.analysis_product,
        instrument_profile=bundle.instrument_profile,
        subject_quality=bundle.subject.quality,
        reference_quality=bundle.reference.quality if bundle.reference else None,
        alignment=bundle.alignment,
        subject_indicators=_latest_indicator_values(subject_evaluation.frame if subject_evaluation else None),
        reference_indicators=_latest_indicator_values(reference_evaluation.frame if reference_evaluation else None),
        subject_signals=subject_evaluation.signals if subject_evaluation else [],
        reference_signals=reference_evaluation.signals if reference_evaluation else [],
        relative_metrics=relative_metrics,
        product_assessment=assessment_payload,
        unavailable_capabilities=unavailable_capabilities or {},
        bundle_snapshot_id=bundle.bundle_snapshot_id,
        versions={
            **bundle.versions,
            "product_rules": "technical-products-v2",
            "relative_rules": "relative-signal-rules-v1",
        },
    )


def _quality_line(label: str, quality: DataQualityReport | None) -> str:
    if quality is None:
        return f"{label}：不可得"
    return f"{label}：{quality.grade} / {quality.source_status} / {quality.decision}"


def render_product_evidence_bundle(bundle: ProductTechnicalEvidenceBundle) -> str:
    """Render a bounded three-section report without unsafe financial terms."""

    assessment = bundle.product_assessment
    lines = [
        f"分析产品：{bundle.analysis_product}",
        _quality_line("主体数据", bundle.subject_quality),
        _quality_line("参考数据", bundle.reference_quality),
        f"组合快照：{bundle.bundle_snapshot_id}",
        f"产品状态：{assessment.get('product_state', 'unavailable')}",
        f"产品置信度：{assessment.get('confidence', 0)}",
        "",
    ]
    if bundle.analysis_product == "passive_equity_etf":
        lines.extend([
            "## 跟踪指数",
            f"技术状态：{assessment.get('reference_stance', 'unavailable')}",
            "指数成交量类指标：禁用（成交量统计口径未验证）",
            "",
            "## ETF 市场价格",
            f"技术状态：{assessment.get('subject_stance', 'unavailable')}",
            f"流动性状态：{assessment.get('liquidity_state', 'unavailable')}",
            "",
            "## 二者关系",
            f"价格路径状态：{assessment.get('alignment_state', 'unavailable')}",
            "关系指标语义：市场价格收益差、价格路径一致性和相对强弱；不代表净值或正式跟踪质量。",
        ])
    elif bundle.analysis_product == "active_equity_etf":
        lines.extend([
            "## 主动管理 ETF",
            f"ETF 自身技术状态：{assessment.get('subject_stance', 'unavailable')}",
            f"流动性状态：{assessment.get('liquidity_state', 'unavailable')}",
            "正式比较基准仅作为相对强弱背景，不生成机械跟踪一致性。",
        ])
    elif bundle.analysis_product == "a_share_stock":
        lines.extend([
            "## 普通 A 股",
            f"自身技术状态：{assessment.get('subject_stance', 'unavailable')}",
            "可选基准只调整相对强弱背景，不覆盖股票自身信号。",
        ])
    else:
        lines.extend([
            "## 指数子报告",
            f"技术状态：{assessment.get('subject_stance', 'unavailable')}",
            "指数不单独输出可执行交易评级。",
        ])
    if bundle.alignment is not None:
        lines.append(
            f"共同观察：{bundle.alignment.common_observations} / coverage={bundle.alignment.common_coverage:.4f}"
        )
    if bundle.unavailable_capabilities:
        lines.extend(["", "数据限制："])
        lines.extend(f"- {key}：{value}" for key, value in bundle.unavailable_capabilities.items())
    if bundle.subject_quality.decision != "allow":
        lines.append("数据不足时只显示 unavailable/observe_only，不将其改写为 Hold。")
    return "\n".join(lines)
