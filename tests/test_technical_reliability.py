"""Offline acceptance tests for the deterministic technical path."""

from datetime import date, datetime, timezone
from decimal import Decimal
import shutil
from pathlib import Path

import pandas as pd
import pytest

from tradingagents.dataflows.market_data_service import MarketDataService
from tradingagents.dataflows.models import MarketDataRequest, NormalizedBar, VendorBarsResult
from tradingagents.dataflows.snapshots import SnapshotStore
from tradingagents.dataflows.validation import check_cross_source_consistency, validate_bars
from tradingagents.dataflows.vendors.base import VendorTimeout
from tradingagents.evaluation.technical_signal_evaluator import evaluate_samples, label_signal
from tradingagents.technical.evidence import build_evidence_bundle, render_evidence_bundle
from tradingagents.technical.indicators import IndicatorEngine
from tradingagents.technical.signals import SignalEngine


def _request():
    return MarketDataRequest(
        symbol="600000",
        exchange="SSE",
        instrument_type="stock",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        adjustment="raw",
        as_of=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )


def _bar(day, close=10, source="test", adjustment="raw"):
    close = Decimal(str(close))
    return NormalizedBar(
        symbol="600000",
        trade_date=day,
        open=close,
        high=close + 1,
        low=close - Decimal("0.5"),
        close=close,
        volume=Decimal("1000"),
        adjustment=adjustment,
        source=source,
        source_symbol="600000",
        retrieved_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )


def test_validation_rejects_invalid_ohlc_without_repairing_it():
    invalid = _bar(date(2024, 1, 2))
    invalid = invalid.model_copy(update={"high": Decimal("9")})
    result = validate_bars([invalid], _request())
    assert result.bars == []
    assert result.invalid_rows == 1
    assert any(flag.startswith("invalid_ohlc") for flag in result.flags)


def test_cross_source_conflict_is_explicit():
    left = [_bar(date(2024, 1, 2), 10, "mootdx")]
    right = [_bar(date(2024, 1, 2), 11, "sina")]
    conflicts = check_cross_source_consistency(left, right, price_tolerance=0.01)
    assert conflicts and "close" in conflicts[0].fields


def test_indicator_and_signal_results_are_repeatable():
    dates = pd.bdate_range("2023-01-01", periods=220)
    bars = [_bar(timestamp.date(), 10 + index * 0.03) for index, timestamp in enumerate(dates)]
    engine = IndicatorEngine()
    first = engine.calculate_frame(bars)
    second = engine.calculate_frame(bars)
    pd.testing.assert_frame_equal(first, second)
    first_eval = SignalEngine().run(first, quality_grade="A")
    second_eval = SignalEngine().run(second, quality_grade="A")
    assert [item.model_dump() for item in first_eval.signals] == [item.model_dump() for item in second_eval.signals]
    assert first_eval.assessment == second_eval.assessment


def test_quality_grade_c_is_observation_only_and_d_is_unavailable():
    dates = pd.bdate_range("2023-01-01", periods=220)
    bars = [_bar(timestamp.date(), 10 + index * 0.03) for index, timestamp in enumerate(dates)]
    frame = IndicatorEngine().calculate_frame(bars)
    assert SignalEngine().run(frame, quality_grade="C").assessment.decision == "observe_only"
    assert SignalEngine().run(frame, quality_grade="D").assessment.stance == "unavailable"


def test_evidence_renderer_discloses_snapshot_and_block():
    request = _request()
    result = MarketDataService.__new__(MarketDataService)
    result = type("Result", (), {})()
    # Use the real model while keeping this test fully offline.
    from tradingagents.dataflows.models import DataQualityReport, MarketDataResult, SourceAttempt

    market_result = MarketDataResult(
        request=request,
        bars=[_bar(date(2024, 1, 2))],
        attempts=[SourceAttempt(source="mootdx", started_at=datetime(2024, 2, 1, tzinfo=timezone.utc), status="timeout")],
        quality=DataQualityReport(grade="F", decision="block", source_status="UNAVAILABLE", flags=["timeout"]),
        snapshot_id="sha256:test",
    )
    bundle = build_evidence_bundle(market_result)
    report = render_evidence_bundle(bundle)
    assert "sha256:test" in report
    assert "block" in report


def test_evaluator_labels_future_returns_without_trading_metrics():
    dates = pd.bdate_range("2024-01-01", periods=70)
    prices = {timestamp.date(): 100 + index for index, timestamp in enumerate(dates)}
    sample = label_signal(
        symbol="600000",
        signal_date=dates[0].date(),
        snapshot_id="sha256:fixed",
        data_quality_grade="A",
        technical_stance="bullish",
        technical_score=0.8,
        confidence=0.9,
        rule_version="technical-signal-v1",
        prices=prices,
    )
    result = evaluate_samples([sample])
    assert sample.forward_return_5d == pytest.approx(0.05)
    assert result["non_trading_evaluation"] is True
    assert "sharpe" not in str(result).lower()


def test_service_falls_back_after_timeout(tmp_path):
    class Primary:
        name = "mootdx"
        capabilities = None

        def fetch_bars(self, request):
            raise VendorTimeout("timed out")

    class Fallback:
        name = "sina"
        capabilities = None

        def fetch_bars(self, request):
            return VendorBarsResult(source="sina", bars=[_bar(date(2024, 1, 2), source="sina")])

    request = _request().model_copy(update={"end_date": date(2024, 1, 2)})
    root = Path.cwd() / ".pytest-snapshot-service"
    try:
        service = MarketDataService(
            {"mootdx": Primary(), "sina": Fallback()},
            snapshot_store=SnapshotStore(root),
            config={"market_data_policy": {"stock_daily": ["mootdx", "sina"], "max_attempts": 2}},
        )
        result = service.fetch(request)
        assert result.attempts[0].status == "timeout"
        assert result.attempts[1].status == "success"
        assert result.quality.source_status == "FALLBACK_OK"
        assert result.snapshot_id
        loaded = service.snapshot_store.load(result.snapshot_id)
        assert loaded.request == request
        assert loaded.bars == result.bars
    finally:
        shutil.rmtree(root, ignore_errors=True)
