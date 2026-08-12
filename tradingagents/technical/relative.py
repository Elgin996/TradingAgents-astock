"""Cross-series metrics for ETF/index or stock/benchmark relationships.

All functions operate on the intersection of dates already present in both
series.  They never forward-fill, back-fill, substitute an index return for a
missing ETF observation, or label a market-price difference as formal tracking
quality.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from tradingagents.dataflows.models import (
    AnalysisMarketDataBundle,
    MarketDataResult,
    RelativeMetric,
    SeriesAlignmentReport,
    TechnicalAssessment,
)


RELATIVE_RULE_VERSION = "relative-signal-rules-v1"


def _series(value, name: str) -> pd.Series:
    if isinstance(value, MarketDataResult):
        bars = value.bars
    else:
        bars = value
    rows = []
    for bar in bars or []:
        if hasattr(bar, "trade_date"):
            rows.append((bar.trade_date, float(bar.close)))
        else:
            rows.append((bar["trade_date"], float(bar["close"])))
    if not rows:
        return pd.Series(dtype=float, name=name)
    frame = pd.DataFrame(rows, columns=["trade_date", name])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
    frame = frame.dropna(subset=["trade_date", name]).drop_duplicates("trade_date", keep="first")
    return frame.set_index("trade_date")[name].sort_index()


def align_price_series(
    subject: MarketDataResult | Sequence,
    reference: MarketDataResult | Sequence,
) -> pd.DataFrame:
    """Return only the common observed dates; no values are synthesized."""

    left = _series(subject, "subject_close")
    right = _series(reference, "reference_close")
    if left.empty or right.empty:
        return pd.DataFrame(columns=["subject_close", "reference_close"])
    return pd.concat([left, right], axis=1, join="inner").dropna().sort_index()


def _status(value: float | None, common: int, required: int = 2) -> str:
    if common < required:
        return "insufficient"
    return "ok" if value is not None and np.isfinite(value) else "insufficient"


def _semantics(subject: MarketDataResult, reference: MarketDataResult) -> str:
    subject_label = "market price" if subject.request.instrument_type == "etf" else "subject price"
    reference_variant = reference.request.series_variant
    reference_label = {
        "price": "price index",
        "total_return": "total-return index",
        "net_total_return": "net-total-return index",
    }.get(reference_variant, "reference series")
    return f"{subject_label} vs {reference_label}"


def _make_metric(
    *,
    metric_id: str,
    value: float | None,
    window: int | None,
    as_of: date,
    subject: MarketDataResult,
    reference: MarketDataResult,
    common: int,
    semantics: str,
    status: str,
    rule_version: str,
) -> RelativeMetric:
    return RelativeMetric(
        metric_id=metric_id,
        value=value,
        window=window,
        as_of=as_of,
        subject_snapshot_id=subject.snapshot_id or "",
        reference_snapshot_id=reference.snapshot_id or "",
        common_observations=common,
        status=status,
        semantics=semantics,
        rule_version=rule_version,
    )


def calculate_relative_metrics(
    subject: MarketDataResult,
    reference: MarketDataResult,
    *,
    alignment: SeriesAlignmentReport | None = None,
    windows: Iterable[int] = (20, 60),
    rule_version: str = RELATIVE_RULE_VERSION,
) -> list[RelativeMetric]:
    common = align_price_series(subject, reference)
    common_count = len(common)
    as_of = common.index[-1] if common_count else min(subject.request.end_date, reference.request.end_date)
    as_of = date.fromisoformat(as_of.isoformat()) if hasattr(as_of, "isoformat") else as_of
    semantics = _semantics(subject, reference)
    blocked = (
        (alignment is not None and alignment.decision != "allow")
        or reference.request.series_variant == "unknown"
        or subject.request.series_variant == "unknown"
    )
    metrics: list[RelativeMetric] = []

    cumulative = None
    if common_count >= 2 and not blocked:
        subject_return = common["subject_close"].iloc[-1] / common["subject_close"].iloc[0] - 1
        reference_return = common["reference_close"].iloc[-1] / common["reference_close"].iloc[0] - 1
        cumulative = float(subject_return - reference_return)
    metrics.append(
        _make_metric(
            metric_id="market_price_return_difference",
            value=cumulative,
            window=None,
            as_of=as_of,
            subject=subject,
            reference=reference,
            common=common_count,
            semantics=f"共同区间累计收益差（{semantics}）",
            status="blocked" if blocked else _status(cumulative, common_count),
            rule_version=rule_version,
        )
    )

    returns = common.pct_change().dropna()
    for window in tuple(dict.fromkeys(int(item) for item in windows if int(item) > 1)):
        corr = beta = strength = volatility = None
        if not blocked and len(returns) >= window:
            left = returns["subject_close"].iloc[-window:]
            right = returns["reference_close"].iloc[-window:]
            right_variance = float(right.var(ddof=0))
            corr = float(left.corr(right)) if right_variance > 0 else None
            beta = float(left.cov(right, ddof=0) / right_variance) if right_variance > 1e-18 else None
            volatility = float((left - right).std(ddof=0))
            left_start = common["subject_close"].iloc[-window - 1]
            right_start = common["reference_close"].iloc[-window - 1]
            left_norm = common["subject_close"].iloc[-1] / left_start
            right_norm = common["reference_close"].iloc[-1] / right_start
            strength = float(left_norm / right_norm) if right_norm else None
        status = "blocked" if blocked else _status(corr, common_count, window + 1)
        metrics.append(_make_metric(
            metric_id="rolling_return_correlation",
            value=corr,
            window=window,
            as_of=as_of,
            subject=subject,
            reference=reference,
            common=common_count,
            semantics=f"滚动收益相关系数（{semantics}）",
            status=status,
            rule_version=rule_version,
        ))
        metrics.append(_make_metric(
            metric_id="rolling_return_beta",
            value=beta,
            window=window,
            as_of=as_of,
            subject=subject,
            reference=reference,
            common=common_count,
            semantics=f"滚动收益敏感度 beta（{semantics}）",
            status="blocked" if blocked else _status(beta, common_count, window + 1),
            rule_version=rule_version,
        ))
        metrics.append(_make_metric(
            metric_id="normalized_relative_strength",
            value=strength,
            window=window,
            as_of=as_of,
            subject=subject,
            reference=reference,
            common=common_count,
            semantics=f"归一化相对强弱线（{semantics}）",
            status="blocked" if blocked else _status(strength, common_count, window + 1),
            rule_version=rule_version,
        ))
        metrics.append(_make_metric(
            metric_id="market_price_return_difference_volatility",
            value=volatility,
            window=window,
            as_of=as_of,
            subject=subject,
            reference=reference,
            common=common_count,
            semantics=f"市场价格收益差波动（{semantics}）",
            status="blocked" if blocked else _status(volatility, common_count, window + 1),
            rule_version=rule_version,
        ))
        direction = None
        if not blocked and len(returns) >= window:
            left = returns["subject_close"].iloc[-window:]
            right = returns["reference_close"].iloc[-window:]
            direction = float((np.sign(left) == np.sign(right)).mean())
        metrics.append(_make_metric(
            metric_id="direction_consistency_rate",
            value=direction,
            window=window,
            as_of=as_of,
            subject=subject,
            reference=reference,
            common=common_count,
            semantics=f"共同交易日方向一致率（{semantics}）",
            status="blocked" if blocked else _status(direction, common_count, window + 1),
            rule_version=rule_version,
        ))
    return metrics


def technical_state_consistency(
    subject_assessment: TechnicalAssessment | None,
    reference_assessment: TechnicalAssessment | None,
    *,
    bundle: AnalysisMarketDataBundle | None = None,
    rule_version: str = RELATIVE_RULE_VERSION,
) -> RelativeMetric:
    """Encode stance agreement as an auditable descriptive metric."""

    as_of = (
        bundle.alignment.end_date
        if bundle is not None and bundle.alignment and bundle.alignment.end_date
        else date.today()
    )
    common = bundle.alignment.common_observations if bundle and bundle.alignment else 0
    subject_snapshot = bundle.subject.snapshot_id if bundle else (subject_assessment.snapshot_id if subject_assessment else "")
    reference_snapshot = bundle.reference.snapshot_id if bundle and bundle.reference else ""
    value = None
    status = "blocked"
    if (
        subject_assessment
        and reference_assessment
        and common
        and (bundle is None or bundle.alignment is None or bundle.alignment.decision == "allow")
    ):
        if subject_assessment.stance in {"bullish", "bearish", "neutral", "mixed"} and reference_assessment.stance in {"bullish", "bearish", "neutral", "mixed"}:
            value = 1.0 if subject_assessment.stance == reference_assessment.stance else 0.0
            status = "ok"
    return RelativeMetric(
        metric_id="technical_state_consistency",
        value=value,
        window=None,
        as_of=as_of,
        subject_snapshot_id=subject_snapshot or "",
        reference_snapshot_id=reference_snapshot or "",
        common_observations=common,
        status=status,
        semantics="subject technical stance vs reference technical stance",
        rule_version=rule_version,
    )
