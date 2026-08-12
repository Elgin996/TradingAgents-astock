from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from tradingagents.dataflows.models import DataQualityReport, TechnicalAssessment
from tradingagents.technical.products import (
    assess_passive_etf,
    calculate_product_indicator_frame,
    evaluate_product_signals,
    infer_liquidity_state,
)
from tradingagents.dataflows.models import SeriesAlignmentReport


def _bars():
    rows = []
    for index in range(240):
        day = date(2024, 1, 1) + timedelta(days=index)
        close = Decimal(str(10 + index * 0.02))
        rows.append({
            "trade_date": day,
            "open": close,
            "high": close + Decimal("0.1"),
            "low": close - Decimal("0.1"),
            "close": close,
            "volume": Decimal("1000"),
            "amount": Decimal("10000"),
        })
    return rows


def _assessment(stance):
    return TechnicalAssessment(
        stance=stance,
        score=0.8 if stance == "bullish" else -0.8 if stance == "bearish" else 0,
        confidence=0.9,
        decision="allow",
        data_quality_grade="A",
        indicator_config_version="indicator-config-v1",
        signal_rule_version="technical-signal-v1",
    )


def test_index_product_removes_volume_indicators_and_signals():
    frame = calculate_product_indicator_frame(_bars(), "index")
    assert "volume_20_sma" not in frame.columns
    evaluation = evaluate_product_signals(_bars(), "index")
    assert all(signal.category != "volume" for signal in evaluation.signals)


def test_etf_liquidity_state_uses_observed_amount_or_volume_only():
    etf_frame = calculate_product_indicator_frame(_bars(), "passive_equity_etf")
    index_frame = calculate_product_indicator_frame(_bars(), "index")
    assert infer_liquidity_state(etf_frame, "passive_equity_etf") == "available"
    assert infer_liquidity_state(index_frame, "index") == "unavailable"


def test_passive_assessment_preserves_confirmed_and_conflicted_states():
    alignment = SeriesAlignmentReport(
        subject_observations=220,
        reference_observations=220,
        common_observations=220,
        common_coverage=1,
        subject_series_variant="market_price",
        reference_series_variant="price",
        decision="allow",
    )
    confirmed = assess_passive_etf(_assessment("bullish"), _assessment("bullish"), alignment)
    conflicted = assess_passive_etf(_assessment("bearish"), _assessment("bullish"), alignment)
    assert confirmed.product_state == "bullish_confirmed"
    assert conflicted.product_state == "conflicted"
    assert conflicted.decision == "observe_only"
