from datetime import date, datetime, timezone
from decimal import Decimal

from tradingagents.dataflows.analysis_bundle import (
    build_analysis_market_data_bundle,
    rebuild_bundle_snapshot,
    align_series,
)
from tradingagents.dataflows.models import (
    DataQualityReport,
    MarketDataRequest,
    MarketDataResult,
    NormalizedBar,
)


def _result(symbol, instrument_type, days, *, variant="market_price", grade="A", decision="allow"):
    request = MarketDataRequest(
        symbol=symbol,
        exchange="SSE",
        instrument_type=instrument_type,
        start_date=min(days),
        end_date=max(days),
        adjustment="raw",
        as_of=datetime.combine(max(days), datetime.min.time(), tzinfo=timezone.utc),
        series_variant=variant,
    )
    bars = [
        NormalizedBar(
            symbol=symbol,
            trade_date=day,
            open=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal(str(10 + index / 10)),
            volume=Decimal("100"),
            adjustment="raw",
            source="fixture",
            source_symbol=symbol,
            retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        for index, day in enumerate(days)
    ]
    return MarketDataResult(
        request=request,
        bars=bars,
        quality=DataQualityReport(
            grade=grade,
            decision=decision,
            source_status="PRIMARY_OK",
            completeness_score=1,
            freshness_score=1,
            consistency_score=1,
            semantics_score=1,
        ),
        snapshot_id=f"sha256:{symbol}",
    )


def test_alignment_uses_intersection_without_fill():
    left_days = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    right_days = [date(2024, 1, 1), date(2024, 1, 3)]
    report = align_series(
        _result("510300", "etf", left_days),
        _result("000300", "index", right_days, variant="price"),
        min_common_observations=2,
        min_coverage=0.5,
    )
    assert report.common_observations == 2
    assert report.subject_only_dates == [date(2024, 1, 2)]
    assert report.reference_only_dates == []
    assert report.decision == "allow"


def test_passive_missing_reference_is_observation_only_and_rebuildable():
    days = [date(2024, 1, index + 1) for index in range(25)]
    subject = _result("510300", "etf", days)
    bundle = build_analysis_market_data_bundle(
        subject,
        analysis_product="passive_equity_etf",
        instrument_profile={"analysis_product": "passive_equity_etf"},
    )
    assert bundle.overall_decision == "observe_only"
    assert "passive_tracking_reference_missing" in bundle.flags
    assert rebuild_bundle_snapshot(bundle) == bundle.bundle_snapshot_id
