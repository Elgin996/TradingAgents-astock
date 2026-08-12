"""Walk-forward signal labels and descriptive statistics.

This module deliberately does not construct a portfolio or model execution
constraints.  Future prices are attached only as post-hoc labels to an
already-frozen signal sample.
"""

from __future__ import annotations

import math
import random
from datetime import date
from statistics import mean, median
from typing import Iterable, Mapping, Sequence

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class TechnicalSignalSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    signal_date: date
    snapshot_id: str
    data_quality_grade: str
    source_status: str = ""
    technical_stance: str
    technical_score: float
    confidence: float
    rule_version: str
    forward_return_5d: float | None = None
    forward_return_20d: float | None = None
    forward_return_60d: float | None = None
    benchmark_return_5d: float | None = None
    benchmark_return_20d: float | None = None
    benchmark_return_60d: float | None = None
    forward_alpha_5d: float | None = None
    forward_alpha_20d: float | None = None
    forward_alpha_60d: float | None = None


def _future_return(prices: pd.Series, signal_date: date, horizon: int) -> float | None:
    series = prices.copy()
    series.index = pd.to_datetime(series.index).date
    series = series.sort_index()
    available = [item for item in series.index if item >= signal_date]
    if not available:
        return None
    start = series.loc[available[0]]
    future = [item for item in series.index if item > available[0]]
    if len(future) < horizon or start in (None, 0) or pd.isna(start):
        return None
    end = series.loc[future[horizon - 1]]
    if pd.isna(end):
        return None
    return float(end / start - 1)


def label_signal(
    *,
    symbol: str,
    signal_date: date | str,
    snapshot_id: str,
    data_quality_grade: str,
    technical_stance: str,
    technical_score: float,
    confidence: float,
    rule_version: str,
    prices: Mapping,
    benchmark_prices: Mapping | None = None,
    source_status: str = "",
) -> TechnicalSignalSample:
    signal_date = date.fromisoformat(signal_date) if isinstance(signal_date, str) else signal_date
    prices = pd.Series(prices)
    benchmark = pd.Series(benchmark_prices) if benchmark_prices is not None else None
    values = {}
    for horizon in (5, 20, 60):
        values[f"forward_return_{horizon}d"] = _future_return(prices, signal_date, horizon)
        values[f"benchmark_return_{horizon}d"] = _future_return(benchmark, signal_date, horizon) if benchmark is not None else None
        forward = values[f"forward_return_{horizon}d"]
        benchmark_value = values[f"benchmark_return_{horizon}d"]
        values[f"forward_alpha_{horizon}d"] = forward - benchmark_value if forward is not None and benchmark_value is not None else None
    return TechnicalSignalSample(
        symbol=symbol,
        signal_date=signal_date,
        snapshot_id=snapshot_id,
        data_quality_grade=data_quality_grade,
        source_status=source_status,
        technical_stance=technical_stance,
        technical_score=technical_score,
        confidence=confidence,
        rule_version=rule_version,
        **values,
    )


def _direction_correct(stance: str, value: float | None) -> bool | None:
    if value is None:
        return None
    if stance == "bullish":
        return value > 0
    if stance == "bearish":
        return value < 0
    if stance in {"neutral", "mixed"}:
        return abs(value) < 0.01
    return None


def _bootstrap_interval(values: Sequence[float], iterations: int = 500) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    rng = random.Random(0)
    means = [mean(rng.choices(list(values), k=len(values))) for _ in range(iterations)]
    means.sort()
    return means[int(0.025 * len(means))], means[int(0.975 * len(means))]


def _summary(samples: Sequence[TechnicalSignalSample], horizon: int) -> dict:
    returns = [getattr(sample, f"forward_return_{horizon}d") for sample in samples]
    returns = [float(value) for value in returns if value is not None]
    alpha = [getattr(sample, f"forward_alpha_{horizon}d") for sample in samples]
    alpha = [float(value) for value in alpha if value is not None]
    accuracy = [_direction_correct(sample.technical_stance, getattr(sample, f"forward_return_{horizon}d")) for sample in samples]
    accuracy_values = [value for value in accuracy if value is not None]
    ci = _bootstrap_interval([1.0 if value else 0.0 for value in accuracy_values])
    return {
        "sample_size": len(returns),
        "direction_accuracy": mean(accuracy_values) if accuracy_values else None,
        "avg_return": mean(returns) if returns else None,
        "median_return": median(returns) if returns else None,
        "avg_alpha": mean(alpha) if alpha else None,
        "accuracy_bootstrap_ci95": ci,
        "exploratory": len(returns) < 30,
    }


def evaluate_samples(samples: Iterable[TechnicalSignalSample | Mapping]) -> dict:
    rows = [sample if isinstance(sample, TechnicalSignalSample) else TechnicalSignalSample.model_validate(sample) for sample in samples]
    result = {
        "sample_size": len(rows),
        "coverage": (sum(sample.technical_stance not in {"neutral", "mixed", "unavailable"} for sample in rows) / len(rows)) if rows else 0.0,
        "stance_distribution": {},
        "by_quality": {},
        "by_source": {},
        "by_confidence": {},
        "by_horizon": {str(horizon): _summary(rows, horizon) for horizon in (5, 20, 60)},
        "rule_versions": sorted({sample.rule_version for sample in rows}),
        "non_trading_evaluation": True,
    }
    for sample in rows:
        result["stance_distribution"][sample.technical_stance] = result["stance_distribution"].get(sample.technical_stance, 0) + 1
        result["by_quality"].setdefault(sample.data_quality_grade, []).append(sample)
        result["by_source"].setdefault(sample.source_status or "unknown", []).append(sample)
        bucket = "high" if sample.confidence >= 0.75 else "medium" if sample.confidence >= 0.4 else "low"
        result["by_confidence"].setdefault(bucket, []).append(sample)
    for key in ("by_quality", "by_source", "by_confidence"):
        result[key] = {
            group: {str(horizon): _summary(group_rows, horizon) for horizon in (5, 20, 60)}
            for group, group_rows in result[key].items()
        }
    return result


class TechnicalSignalEvaluator:
    """Facade that makes the evaluation contract explicit in call sites."""

    def label(self, **kwargs) -> TechnicalSignalSample:
        return label_signal(**kwargs)

    def evaluate(self, samples: Iterable[TechnicalSignalSample | Mapping]) -> dict:
        return evaluate_samples(samples)

