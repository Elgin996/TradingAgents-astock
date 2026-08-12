"""Deterministic technical evidence rules; no model or network calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd

from tradingagents.dataflows.models import TechnicalAssessment, TechnicalSignal
from .indicators import IndicatorConfig, IndicatorEngine, calculate_indicator_frame


SIGNAL_RULE_VERSION = "technical-signal-v1"
_QUALITY_CONFIDENCE = {"A": 1.0, "B": 0.8, "C": 0.5, "D": 0.0, "F": 0.0}


def _number(row: pd.Series, name: str) -> float | None:
    value = row.get(name)
    if value is None or pd.isna(value):
        return None
    return float(value)


def _signal(
    signal_id: str,
    category: str,
    direction: str,
    strength: float,
    confidence: float,
    observed_at: date,
    inputs: dict,
    explanation_key: str,
) -> TechnicalSignal:
    return TechnicalSignal(
        signal_id=signal_id,
        category=category,
        direction=direction,
        strength=max(0.0, min(1.0, strength)),
        confidence=max(0.0, min(1.0, confidence)),
        observed_at=observed_at,
        inputs={key: (None if value is None else float(value) if isinstance(value, (int, float)) else str(value)) for key, value in inputs.items()},
        rule_version=SIGNAL_RULE_VERSION,
        explanation_key=explanation_key,
    )


def _relative_strength(close: float, reference: float) -> float:
    return min(1.0, abs(close - reference) / max(abs(reference), 1e-9) * 10)


def generate_signals(
    frame: pd.DataFrame,
    *,
    quality_grade: str = "A",
    rule_version: str = SIGNAL_RULE_VERSION,
) -> list[TechnicalSignal]:
    """Generate the same signal list for the same indicator frame."""
    if frame is None or frame.empty:
        return []
    row = frame.iloc[-1]
    observed_at = pd.Timestamp(row["trade_date"]).date()
    quality_confidence = _QUALITY_CONFIDENCE.get(quality_grade, 0.0)
    signals: list[TechnicalSignal] = []

    close = _number(row, "close")
    for period in (20, 50, 200):
        sma = _number(row, f"close_sma_{period}")
        direction = "unavailable" if close is None or sma is None else ("bullish" if close > sma else "bearish" if close < sma else "neutral")
        signals.append(_signal(f"trend.close_vs_sma{period}", "trend", direction, _relative_strength(close, sma) if close is not None and sma is not None else 0, quality_confidence if sma is not None else 0, observed_at, {"close": close, "sma": sma}, "close_vs_sma"))

    sma20, sma50 = _number(row, "close_sma_20"), _number(row, "close_sma_50")
    alignment = "unavailable" if sma20 is None or sma50 is None else ("bullish" if sma20 > sma50 else "bearish" if sma20 < sma50 else "neutral")
    signals.append(_signal("trend.sma20_sma50_alignment", "trend", alignment, _relative_strength(sma20, sma50) if sma20 is not None and sma50 is not None else 0, quality_confidence if alignment != "unavailable" else 0, observed_at, {"sma20": sma20, "sma50": sma50}, "sma_alignment"))

    ema = _number(row, "close_10_ema")
    previous_ema = _number(frame.iloc[-2], "close_10_ema") if len(frame) > 1 else None
    ema_direction = "unavailable" if close is None or ema is None or previous_ema is None else ("bullish" if close > ema and ema >= previous_ema else "bearish" if close < ema and ema <= previous_ema else "neutral")
    signals.append(_signal("trend.ema10_slope_position", "trend", ema_direction, _relative_strength(close, ema) if close is not None and ema is not None else 0, quality_confidence if ema_direction != "unavailable" else 0, observed_at, {"close": close, "ema10": ema, "previous_ema10": previous_ema}, "ema_slope_position"))

    macd, macds, macdh = _number(row, "macd"), _number(row, "macds"), _number(row, "macdh")
    macd_direction = "unavailable" if macd is None or macds is None else ("bullish" if macd > macds and macd > 0 else "bearish" if macd < macds and macd < 0 else "neutral")
    signals.append(_signal("momentum.macd_state", "momentum", macd_direction, min(1.0, abs(macdh or 0) / max(abs(macd or 0), 1e-9)), quality_confidence if macd_direction != "unavailable" else 0, observed_at, {"macd": macd, "signal": macds, "histogram": macdh}, "macd_state"))

    rsi = _number(row, "rsi")
    rsi_direction = "unavailable" if rsi is None else ("bullish" if 50 <= rsi < 70 else "bearish" if 30 < rsi < 50 else "neutral")
    rsi_strength = abs(rsi - 50) / 50 if rsi is not None else 0
    signals.append(_signal("momentum.rsi_regime", "momentum", rsi_direction, rsi_strength, quality_confidence if rsi is not None else 0, observed_at, {"rsi": rsi}, "rsi_regime"))

    boll, upper, lower = _number(row, "boll"), _number(row, "boll_ub"), _number(row, "boll_lb")
    if close is None or upper is None or lower is None or upper == lower:
        boll_direction, boll_position, boll_strength = "unavailable", None, 0.0
    else:
        boll_position = (close - lower) / (upper - lower)
        boll_direction = "bullish" if boll_position > 0.8 else "bearish" if boll_position < 0.2 else "neutral"
        boll_strength = min(1.0, abs(boll_position - 0.5) * 2)
    signals.append(_signal("volatility.bollinger_position", "volatility", boll_direction, boll_strength, quality_confidence if boll_direction != "unavailable" else 0, observed_at, {"close": close, "middle": boll, "upper": upper, "lower": lower, "position": boll_position}, "bollinger_position"))

    atr = _number(row, "atr")
    atr_ratio = atr / close if atr is not None and close else None
    signals.append(_signal("volatility.atr_regime", "volatility", "neutral" if atr_ratio is not None else "unavailable", min(1.0, (atr_ratio or 0) * 10), quality_confidence if atr_ratio is not None else 0, observed_at, {"atr": atr, "atr_ratio": atr_ratio}, "atr_regime"))

    vol5, vol20 = _number(row, "volume_5_sma"), _number(row, "volume_20_sma")
    volume_ratio = vol5 / vol20 if vol5 is not None and vol20 not in (None, 0) else None
    volume_direction = "unavailable" if volume_ratio is None else ("bullish" if volume_ratio > 1.2 and close is not None and len(frame) > 1 and close >= float(frame.iloc[-2]["close"]) else "bearish" if volume_ratio > 1.2 else "neutral")
    signals.append(_signal("volume.short_long_ratio", "volume", volume_direction, min(1.0, abs((volume_ratio or 1) - 1) * 2), quality_confidence if volume_ratio is not None else 0, observed_at, {"volume5": vol5, "volume20": vol20, "ratio": volume_ratio}, "volume_confirmation"))

    high20, low20, high60, low60 = (_number(row, key) for key in ("rolling_high_20", "rolling_low_20", "rolling_high_60", "rolling_low_60"))
    if close is None or high20 is None or low20 is None:
        level_direction, level_strength = "unavailable", 0.0
    elif close > high20:
        level_direction, level_strength = "bullish", 1.0
    elif close < low20:
        level_direction, level_strength = "bearish", 1.0
    else:
        level_direction, level_strength = "neutral", 0.0
    signals.append(_signal("level.rolling_breakout20", "level", level_direction, level_strength, quality_confidence if level_direction != "unavailable" else 0, observed_at, {"close": close, "high20": high20, "low20": low20, "high60": high60, "low60": low60}, "rolling_breakout"))
    return signals


@dataclass
class SignalEvaluation:
    signals: list[TechnicalSignal]
    assessment: TechnicalAssessment


def assess_signals(
    signals: Iterable[TechnicalSignal],
    *,
    quality_grade: str = "A",
    snapshot_id: str = "",
    indicator_config_version: str = "indicator-config-v1",
    signal_rule_version: str = SIGNAL_RULE_VERSION,
) -> TechnicalAssessment:
    signals = list(signals)
    usable = [signal for signal in signals if signal.direction != "unavailable" and signal.confidence > 0]
    if not usable or quality_grade in {"D", "F"}:
        return TechnicalAssessment(
            stance="unavailable",
            score=0.0,
            confidence=0.0,
            decision="block",
            data_quality_grade=quality_grade if quality_grade in {"A", "B", "C", "D", "F"} else "F",
            snapshot_id=snapshot_id,
            indicator_config_version=indicator_config_version,
            signal_rule_version=signal_rule_version,
        )
    category_weights = {"trend": 0.30, "momentum": 0.25, "volume": 0.15, "volatility": 0.15, "level": 0.15}
    category_scores: dict[str, float] = {}
    for category, weight in category_weights.items():
        members = [signal for signal in usable if signal.category == category]
        signed = [signal.strength * (1 if signal.direction == "bullish" else -1 if signal.direction == "bearish" else 0) for signal in members]
        category_scores[category] = (sum(signed) / len(signed) if signed else 0.0) * weight
    score = max(-1.0, min(1.0, sum(category_scores.values())))
    bullish = [signal for signal in usable if signal.direction == "bullish"]
    bearish = [signal for signal in usable if signal.direction == "bearish"]
    has_conflict = bool(bullish and bearish and abs(score) < 0.35)
    stance = "mixed" if has_conflict else "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"
    confidence = sum(signal.confidence for signal in usable) / len(usable)
    if quality_grade == "C":
        decision = "observe_only"
    else:
        decision = "allow"
    supporting = [signal.signal_id for signal in usable if (stance == "bullish" and signal.direction == "bullish") or (stance == "bearish" and signal.direction == "bearish")]
    conflicting = [signal.signal_id for signal in usable if (stance == "bullish" and signal.direction == "bearish") or (stance == "bearish" and signal.direction == "bullish") or (stance == "mixed" and signal.direction in {"bullish", "bearish"})]
    return TechnicalAssessment(
        stance=stance,
        score=score,
        confidence=confidence,
        decision=decision,
        supporting_signal_ids=supporting,
        conflicting_signal_ids=conflicting,
        data_quality_grade=quality_grade if quality_grade in {"A", "B", "C", "D", "F"} else "F",
        snapshot_id=snapshot_id,
        indicator_config_version=indicator_config_version,
        signal_rule_version=signal_rule_version,
    )


class SignalEngine:
    rule_version = SIGNAL_RULE_VERSION

    def __init__(self, indicator_config: IndicatorConfig | None = None):
        self.indicator_engine = IndicatorEngine(indicator_config)

    def run(self, bars_or_frame, *, quality_grade: str = "A", snapshot_id: str = "") -> SignalEvaluation:
        frame = bars_or_frame if isinstance(bars_or_frame, pd.DataFrame) else self.indicator_engine.calculate_frame(bars_or_frame)
        signals = generate_signals(frame, quality_grade=quality_grade, rule_version=self.rule_version)
        assessment = assess_signals(
            signals,
            quality_grade=quality_grade,
            snapshot_id=snapshot_id,
            indicator_config_version=self.indicator_engine.config.version,
            signal_rule_version=self.rule_version,
        )
        return SignalEvaluation(signals, assessment)

    def evaluate(self, bars_or_frame, **kwargs) -> TechnicalAssessment:
        return self.run(bars_or_frame, **kwargs).assessment

