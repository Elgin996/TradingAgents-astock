"""Product-aware indicator, signal, and assessment rules for v2.

The calculation remains deterministic and network-free.  Product semantics
live in ``config/technical_products_v2.yaml`` so an index cannot accidentally
inherit ETF volume conclusions and an active ETF cannot inherit tracking
alignment language.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from tradingagents.dataflows.config import load_project_versioned_config
from tradingagents.dataflows.models import (
    AnalysisMarketDataBundle,
    QualityDecision,
    QualityGrade,
    RelativeMetric,
    SeriesAlignmentReport,
    TechnicalAssessment,
    TechnicalSignal,
)
from .indicators import IndicatorConfig, calculate_indicator_frame, load_indicator_config
from .signals import SignalEvaluation, assess_signals, generate_signals


PRODUCT_RULE_VERSION = "product-technical-rules-v2"
_QUALITY_RANK = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
_QUALITY_CONFIDENCE = {"A": 1.0, "B": 0.8, "C": 0.5, "D": 0.0, "F": 0.0}


class ProductSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    security_type: Literal["stock", "etf", "index"]
    indicator_config: str = "indicator-config-v1"
    enabled_categories: tuple[str, ...]
    volume_enabled: bool = True
    amount_enabled: bool = False
    min_warmup: int = Field(default=220, ge=0)
    relation_enabled: bool = False
    reference_role: Literal["tracking_index", "benchmark"] | None = None


class ProductTechnicalAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_product: str
    product_state: str
    stance: str
    confidence: float = Field(ge=0.0, le=1.0)
    decision: QualityDecision
    data_quality_grade: QualityGrade
    subject_stance: str = "unavailable"
    reference_stance: str = "unavailable"
    alignment_state: str = "unavailable"
    liquidity_state: str = "unavailable"
    relative_metrics: list[RelativeMetric] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    rule_version: str = PRODUCT_RULE_VERSION


class StockTechnicalAssessment(ProductTechnicalAssessment):
    analysis_product: Literal["a_share_stock"] = "a_share_stock"


class PassiveEtfTechnicalAssessment(ProductTechnicalAssessment):
    analysis_product: Literal["passive_equity_etf"] = "passive_equity_etf"


class ActiveEtfTechnicalAssessment(ProductTechnicalAssessment):
    analysis_product: Literal["active_equity_etf"] = "active_equity_etf"


@dataclass(frozen=True)
class ProductSignalEvaluation:
    frame: pd.DataFrame
    signals: list[TechnicalSignal]
    assessment: TechnicalAssessment
    spec: ProductSpec


def load_product_specs() -> dict[str, ProductSpec]:
    loaded = load_project_versioned_config("technical_products_v2.yaml")
    raw_products = loaded.get("products")
    if not isinstance(raw_products, dict):
        raise ValueError("technical products config requires a products mapping")
    return {
        name: ProductSpec.model_validate(value)
        for name, value in raw_products.items()
    }


def get_product_spec(analysis_product: str) -> ProductSpec:
    try:
        return load_product_specs()[analysis_product]
    except KeyError as exc:
        raise ValueError(f"unsupported analysis_product: {analysis_product}") from exc


def product_required_warmup(analysis_product: str) -> int:
    return get_product_spec(analysis_product).min_warmup


def _amount_features(frame: pd.DataFrame, spec: ProductSpec) -> pd.DataFrame:
    if not spec.amount_enabled or "amount" not in frame.columns:
        return frame
    amount = pd.to_numeric(frame["amount"], errors="coerce")
    if amount.notna().sum() == 0:
        return frame
    frame["amount_5_sma"] = amount.rolling(5, min_periods=5).mean()
    frame["amount_20_sma"] = amount.rolling(20, min_periods=20).mean()
    frame["amount_percentile_60"] = amount.rolling(60, min_periods=20).rank(pct=True)
    frame["amount_zero_ratio_20"] = (amount.fillna(0) <= 0).rolling(20, min_periods=20).mean()
    if "volume" in frame.columns:
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        frame["volume_observation_ratio_20"] = volume.notna().rolling(20, min_periods=20).mean()
    return frame


def infer_liquidity_state(frame: pd.DataFrame | None, analysis_product: str) -> str:
    """Classify only the availability of ETF trading-activity observations."""

    if analysis_product not in {"passive_equity_etf", "active_equity_etf"}:
        return "unavailable"
    if frame is None or frame.empty:
        return "unavailable"
    candidates = []
    for column in ("amount", "volume"):
        if column in frame.columns:
            values = pd.to_numeric(frame[column], errors="coerce")
            if values.notna().sum() >= 20:
                zero_ratio = float((values.fillna(0) <= 0).tail(20).mean())
                candidates.append(zero_ratio)
    if not candidates:
        return "unavailable"
    return "available" if min(candidates) <= 0.2 else "limited"


def calculate_product_indicator_frame(
    bars,
    analysis_product: str,
    *,
    config: IndicatorConfig | None = None,
) -> pd.DataFrame:
    """Calculate indicators and remove product-ineligible columns/signals."""

    spec = get_product_spec(analysis_product)
    frame = calculate_indicator_frame(bars, config or load_indicator_config())
    if frame.empty:
        return frame
    if not spec.volume_enabled:
        frame = frame.drop(
            columns=[
                name
                for name in (
                    "vwma",
                    "mfi",
                    "volume_5_sma",
                    "volume_20_sma",
                )
                if name in frame.columns
            ]
        )
    frame = _amount_features(frame, spec)
    if not spec.amount_enabled:
        frame = frame.drop(
            columns=[name for name in frame.columns if name.startswith("amount_")],
            errors="ignore",
        )
    return frame


def indicator_values_from_product_frame(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Serialize already-calculated product columns without recalculating v1 volume."""

    if frame is None or frame.empty:
        return {}
    ignored = {"trade_date", "open", "high", "low", "close", "volume", "amount"}
    output: dict[str, list[dict[str, Any]]] = {}
    for name in (column for column in frame.columns if column not in ignored):
        values: list[dict[str, Any]] = []
        for index, (timestamp, value) in enumerate(zip(frame["trade_date"], frame[name])):
            numeric = None if pd.isna(value) else float(value)
            values.append(
                {
                    "name": name,
                    "value": numeric,
                    "trade_date": pd.Timestamp(timestamp).date().isoformat(),
                    "parameters": {},
                    "warmup_complete": numeric is not None,
                    "engine_version": PRODUCT_RULE_VERSION,
                }
            )
        output[name] = values
    return output


def evaluate_product_signals(
    bars_or_frame,
    analysis_product: str,
    *,
    quality_grade: str = "A",
    snapshot_id: str = "",
    config: IndicatorConfig | None = None,
    signal_rules: Mapping[str, Any] | None = None,
) -> ProductSignalEvaluation:
    spec = get_product_spec(analysis_product)
    frame = (
        bars_or_frame
        if isinstance(bars_or_frame, pd.DataFrame)
        else calculate_product_indicator_frame(
            bars_or_frame, analysis_product, config=config
        )
    )
    rules = dict(signal_rules or load_project_versioned_config("signal_rules_v1.yaml"))
    signals = generate_signals(
        frame,
        quality_grade=quality_grade,
        rule_version=PRODUCT_RULE_VERSION,
        enabled_categories=spec.enabled_categories,
    )
    assessment = assess_signals(
        signals,
        quality_grade=quality_grade,
        snapshot_id=snapshot_id,
        indicator_config_version=(config or load_indicator_config()).version,
        signal_rule_version=PRODUCT_RULE_VERSION,
        category_weights={
            key: value
            for key, value in rules.get("weights", {}).items()
            if key in spec.enabled_categories
        },
        observe_only_grades=rules.get("observe_only_grades", ("C",)),
        block_grades=rules.get("block_grades", ("D", "F")),
    )
    return ProductSignalEvaluation(frame, signals, assessment, spec)


def _grade_from_assessments(
    subject: TechnicalAssessment | None,
    reference: TechnicalAssessment | None = None,
) -> QualityGrade:
    grades = [item.data_quality_grade for item in (subject, reference) if item is not None]
    return min(grades, key=lambda value: _QUALITY_RANK.get(value, 0)) if grades else "F"


def _assessment_confidence(assessment: TechnicalAssessment | None) -> float:
    if assessment is None:
        return 0.0
    return float(assessment.confidence) * _QUALITY_CONFIDENCE.get(
        assessment.data_quality_grade, 0.0
    )


def _alignment_state(
    subject: TechnicalAssessment | None,
    reference: TechnicalAssessment | None,
    alignment: SeriesAlignmentReport | None,
) -> str:
    if subject is None or reference is None or alignment is None:
        return "unavailable"
    if alignment.decision != "allow" or not alignment.common_observations:
        return "unavailable"
    left, right = subject.stance, reference.stance
    if left in {"unavailable"} or right in {"unavailable"}:
        return "unavailable"
    if left == right and left in {"bullish", "bearish"}:
        return "consistent"
    if {left, right} == {"bullish", "bearish"}:
        return "divergent"
    return "weak_divergence"


def assess_stock(
    subject_assessment: TechnicalAssessment | None,
    *,
    reference_assessment: TechnicalAssessment | None = None,
    relative_metrics: Iterable[RelativeMetric] = (),
) -> StockTechnicalAssessment:
    stance = subject_assessment.stance if subject_assessment is not None else "unavailable"
    grade = _grade_from_assessments(subject_assessment)
    decision = subject_assessment.decision if subject_assessment is not None else "block"
    flags: list[str] = []
    if reference_assessment is None:
        flags.append("optional_benchmark_unavailable")
    return StockTechnicalAssessment(
        product_state=stance,
        stance=stance,
        confidence=_assessment_confidence(subject_assessment),
        decision=decision,
        data_quality_grade=grade,
        subject_stance=stance,
        reference_stance=reference_assessment.stance if reference_assessment else "unavailable",
        alignment_state=_alignment_state(subject_assessment, reference_assessment, None),
        relative_metrics=list(relative_metrics),
        flags=flags,
    )


def assess_passive_etf(
    subject_assessment: TechnicalAssessment | None,
    reference_assessment: TechnicalAssessment | None,
    alignment: SeriesAlignmentReport | None,
    *,
    liquidity_state: str = "unavailable",
    relative_metrics: Iterable[RelativeMetric] = (),
) -> PassiveEtfTechnicalAssessment:
    vehicle = subject_assessment.stance if subject_assessment else "unavailable"
    underlying = reference_assessment.stance if reference_assessment else "unavailable"
    alignment_state = _alignment_state(subject_assessment, reference_assessment, alignment)
    if vehicle == "unavailable":
        product_state = "unavailable"
    elif underlying == "unavailable":
        product_state = "standalone_vehicle_only"
    elif alignment_state == "consistent" and vehicle == "bullish":
        product_state = "bullish_confirmed"
    elif alignment_state == "consistent" and vehicle == "bearish":
        product_state = "bearish_confirmed"
    elif underlying == "bullish" and vehicle in {"neutral", "mixed"}:
        product_state = "underlying_bullish_vehicle_unconfirmed"
    elif underlying == "bearish" and vehicle in {"neutral", "mixed"}:
        product_state = "underlying_bearish_vehicle_unconfirmed"
    elif alignment_state == "divergent":
        product_state = "conflicted"
    else:
        product_state = "conflicted" if alignment_state != "unavailable" else "standalone_vehicle_only"
    grade = _grade_from_assessments(subject_assessment, reference_assessment)
    confidence_parts = [_assessment_confidence(subject_assessment)]
    if reference_assessment is not None:
        confidence_parts.append(_assessment_confidence(reference_assessment))
    if alignment is not None:
        confidence_parts.append(alignment.common_coverage)
    confidence = sum(confidence_parts) / len(confidence_parts) if confidence_parts else 0.0
    if product_state == "unavailable":
        decision: QualityDecision = "block"
    elif product_state == "conflicted" or underlying == "unavailable":
        decision = "observe_only" if subject_assessment else "block"
    else:
        decision = subject_assessment.decision if subject_assessment else "block"
    flags = []
    if reference_assessment is None:
        flags.append("tracking_index_unavailable")
    if alignment is not None and alignment.decision != "allow":
        flags.extend(alignment.flags)
    return PassiveEtfTechnicalAssessment(
        product_state=product_state,
        stance=vehicle if product_state != "conflicted" else "mixed",
        confidence=max(0.0, min(1.0, confidence)),
        decision=decision,
        data_quality_grade=grade,
        subject_stance=vehicle,
        reference_stance=underlying,
        alignment_state=alignment_state,
        liquidity_state=liquidity_state,
        relative_metrics=list(relative_metrics),
        flags=list(dict.fromkeys(flags)),
    )


def assess_active_etf(
    subject_assessment: TechnicalAssessment | None,
    *,
    benchmark_assessment: TechnicalAssessment | None = None,
    relative_metrics: Iterable[RelativeMetric] = (),
    liquidity_state: str = "unavailable",
) -> ActiveEtfTechnicalAssessment:
    stance = subject_assessment.stance if subject_assessment else "unavailable"
    grade = _grade_from_assessments(subject_assessment)
    return ActiveEtfTechnicalAssessment(
        product_state="standalone_vehicle" if stance != "unavailable" else "unavailable",
        stance=stance,
        confidence=_assessment_confidence(subject_assessment),
        decision=subject_assessment.decision if subject_assessment else "block",
        data_quality_grade=grade,
        subject_stance=stance,
        reference_stance=benchmark_assessment.stance if benchmark_assessment else "unavailable",
        alignment_state="unavailable",
        liquidity_state=liquidity_state,
        relative_metrics=list(relative_metrics),
        flags=["benchmark_optional" if benchmark_assessment is None else "benchmark_context_only"],
    )


def assess_product(
    analysis_product: str,
    subject_assessment: TechnicalAssessment | None,
    *,
    reference_assessment: TechnicalAssessment | None = None,
    alignment: SeriesAlignmentReport | None = None,
    relative_metrics: Iterable[RelativeMetric] = (),
    liquidity_state: str = "unavailable",
) -> ProductTechnicalAssessment:
    if analysis_product == "a_share_stock":
        return assess_stock(
            subject_assessment,
            reference_assessment=reference_assessment,
            relative_metrics=relative_metrics,
        )
    if analysis_product == "passive_equity_etf":
        return assess_passive_etf(
            subject_assessment,
            reference_assessment,
            alignment,
            liquidity_state=liquidity_state,
            relative_metrics=relative_metrics,
        )
    if analysis_product == "active_equity_etf":
        return assess_active_etf(
            subject_assessment,
            benchmark_assessment=reference_assessment,
            relative_metrics=relative_metrics,
            liquidity_state=liquidity_state,
        )
    raise ValueError(f"unsupported analysis_product: {analysis_product}")
