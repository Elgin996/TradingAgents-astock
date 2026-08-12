from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from tradingagents.dataflows.models import (
    DataQualityReport,
    MarketDataRequest,
    MarketDataResult,
    NormalizedBar,
)
from tradingagents.technical.shadow import (
    build_shadow_comparison,
    shadow_mode_enabled,
)


def _subject():
    days = [date(2024, 1, 1) + timedelta(days=index) for index in range(240)]
    request = MarketDataRequest(
        symbol="510300",
        exchange="SSE",
        instrument_type="etf",
        start_date=days[0],
        end_date=days[-1],
        adjustment="raw",
        as_of=datetime.combine(days[-1], datetime.min.time(), tzinfo=timezone.utc),
        series_variant="market_price",
    )
    bars = []
    for index, day in enumerate(days):
        close = Decimal(str(10 + index * 0.02))
        bars.append(
            NormalizedBar(
                symbol="510300",
                trade_date=day,
                open=close,
                high=close + Decimal("0.1"),
                low=close - Decimal("0.1"),
                close=close,
                volume=Decimal("1000"),
                amount=Decimal("10000"),
                adjustment="raw",
                source="fixture",
                source_symbol="510300",
                retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        )
    return MarketDataResult(
        request=request,
        bars=bars,
        quality=DataQualityReport(
            grade="A",
            decision="allow",
            source_status="PRIMARY_OK",
            completeness_score=1,
            freshness_score=1,
            consistency_score=1,
            semantics_score=1,
        ),
        snapshot_id="sha256:subject",
    )


def test_shadow_switch_and_comparison_are_side_channel_only():
    assert shadow_mode_enabled({"technical_v2_shadow_mode": True}, "passive_equity_etf")
    comparison = build_shadow_comparison(
        _subject(),
        analysis_product="passive_equity_etf",
        product_state="bullish_confirmed",
        bundle_snapshot_id="sha256:bundle",
    )
    assert comparison.legacy_snapshot_id == "sha256:subject"
    assert comparison.bundle_snapshot_id == "sha256:bundle"
    assert comparison.v2_state == "bullish_confirmed"
