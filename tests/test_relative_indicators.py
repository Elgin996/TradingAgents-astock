from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from tradingagents.dataflows.analysis_bundle import align_series
from tradingagents.dataflows.models import DataQualityReport, MarketDataRequest, MarketDataResult, NormalizedBar
from tradingagents.technical.relative import calculate_relative_metrics


def _result(symbol, variant, scale=1.0):
    days = [date(2024, 1, 1) + timedelta(days=index) for index in range(80)]
    request = MarketDataRequest(
        symbol=symbol,
        exchange="SSE",
        instrument_type="etf" if symbol == "510300" else "index",
        start_date=days[0],
        end_date=days[-1],
        adjustment="raw",
        as_of=datetime.combine(days[-1], datetime.min.time(), tzinfo=timezone.utc),
        series_variant=variant,
    )
    bars = []
    for index, day in enumerate(days):
        close = Decimal(str(100 + index * scale))
        bars.append(
            NormalizedBar(
                symbol=symbol,
                trade_date=day,
                open=close,
                high=close + 1,
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("100"),
                adjustment="raw",
                source="fixture",
                source_symbol=symbol,
                retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        )
    return MarketDataResult(
        request=request,
        bars=bars,
        quality=DataQualityReport(
            grade="A", decision="allow", source_status="PRIMARY_OK",
            completeness_score=1, freshness_score=1, consistency_score=1, semantics_score=1,
        ),
        snapshot_id=f"sha256:{symbol}",
    )


def test_relative_metrics_have_explicit_market_price_semantics():
    subject = _result("510300", "market_price")
    reference = _result("000300", "price", 0.8)
    alignment = align_series(subject, reference)
    metrics = calculate_relative_metrics(subject, reference, alignment=alignment)
    assert metrics
    assert any(metric.metric_id == "market_price_return_difference" for metric in metrics)
    assert all("正式跟踪" not in metric.semantics for metric in metrics)
    assert any(metric.metric_id == "rolling_return_correlation" and metric.window == 20 and metric.status == "ok" for metric in metrics)


def test_blocked_alignment_blocks_relationship_metrics():
    subject = _result("510300", "market_price")
    reference = _result("000300", "unknown")
    alignment = align_series(subject, reference)
    metrics = calculate_relative_metrics(subject, reference, alignment=alignment)
    assert alignment.decision == "block"
    assert all(metric.status == "blocked" for metric in metrics)
