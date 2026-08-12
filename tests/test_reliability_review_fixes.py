"""Regression coverage for reliability defects found in commit review."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import shutil
import threading
import time
from uuid import uuid4

import pandas as pd
from langchain_core.messages import HumanMessage

from tradingagents.agents.analysts.market_analyst import (
    _a_share_exchange,
    create_market_analyst,
)
from tradingagents.agents.quality_gate import create_quality_gate
from tradingagents.dataflows.market_data_service import MarketDataService
from tradingagents.dataflows.market_data_service import build_technical_evidence
from tradingagents.dataflows.models import (
    DataQualityReport,
    MarketDataRequest,
    MarketDataResult,
    NormalizedBar,
    VendorBarsResult,
)
from tradingagents.dataflows.snapshots import SnapshotStore
from tradingagents.dataflows.validation import build_quality_report, validate_bars
from tradingagents.dataflows.vendors.eastmoney_adapter import EastmoneyAdapter
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.technical.indicators import IndicatorEngine
from tradingagents.technical.evidence import TechnicalEvidenceBundle
from tradingagents.technical.signals import SignalEngine


def _root(name: str) -> Path:
    return Path.cwd() / f".pytest-{name}-{uuid4().hex}"


def _request(*, start=date(2024, 1, 1), end=date(2024, 1, 31), instrument="stock"):
    return MarketDataRequest(
        symbol="510300" if instrument == "etf" else "600000",
        exchange="SSE",
        instrument_type=instrument,
        start_date=start,
        end_date=end,
        adjustment="raw",
        as_of=datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc),
    )


def _bar(day: date, *, symbol="600000", source="fixture", close=10):
    close = Decimal(str(close))
    return NormalizedBar(
        symbol=symbol,
        trade_date=day,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=Decimal("1000"),
        adjustment="raw",
        source=source,
        source_symbol=symbol,
        retrieved_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )


def test_market_route_accepts_human_message_when_deterministic_node_has_no_tools():
    route = ConditionalLogic().should_continue_market({"messages": [HumanMessage(content="600000")]})
    assert route == "Msg Clear Market"


def test_precomputed_market_node_returns_an_ai_message_for_graph_routing():
    bundle = TechnicalEvidenceBundle(
        bundle_id="evidence:test",
        symbol="600000",
        analysis_start=date(2024, 1, 1),
        analysis_end=date(2024, 1, 2),
        data_quality_grade="F",
        data_quality_decision="block",
        source_status="UNAVAILABLE",
    )
    result = create_market_analyst(None)({"technical_evidence_bundle": bundle.model_dump(mode="json")})
    assert result["messages"][0].type == "ai"
    assert ConditionalLogic().should_continue_market(result) == "Msg Clear Market"


def test_market_exchange_resolution_handles_new_bse_prefix():
    assert _a_share_exchange("920819") == "BSE"
    assert _a_share_exchange("600519") == "SSE"
    assert _a_share_exchange("000001") == "SZSE"


def test_eastmoney_passes_requested_adjustment_to_underlying_fetch(monkeypatch):
    captured = {}

    def fake_fetch(symbol, start, end, adjustment):
        captured["adjustment"] = adjustment
        return pd.DataFrame(
            [{"Date": "2024-01-02", "Open": 10, "High": 11, "Low": 9, "Close": 10, "Volume": 100}]
        )

    import tradingagents.dataflows.a_stock as a_stock

    monkeypatch.setattr(a_stock, "_em_kline_with_amount", fake_fetch)
    request = _request(start=date(2024, 1, 2), end=date(2024, 1, 2), instrument="etf")
    result = EastmoneyAdapter().fetch_bars(request)
    assert captured["adjustment"] == "raw"
    assert result.adjustment == "raw"
    assert {bar.adjustment for bar in result.bars} == {"raw"}


def test_missing_exchange_calendar_is_ambiguous_not_a_false_holiday_gap():
    request = _request(start=date(2024, 1, 1), end=date(2024, 1, 2))
    checked = validate_bars([_bar(date(2024, 1, 2))], request)
    report = build_quality_report(checked.bars, request, validation=checked)
    assert checked.missing_dates == []
    assert "calendar_ambiguous" in report.flags
    assert report.grade == "B"


def test_authoritative_exchange_calendar_detects_a_real_gap():
    request = _request(start=date(2024, 1, 2), end=date(2024, 1, 4))
    calendar = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    report = build_quality_report(
        [_bar(date(2024, 1, 2)), _bar(date(2024, 1, 4))],
        request,
        calendar=calendar,
        single_source_unverified=False,
    )
    assert report.missing_dates == [date(2024, 1, 3)]
    assert report.decision == "observe_only"


def test_required_indicator_warmup_blocks_short_history():
    request = _request(start=date(2024, 1, 1), end=date(2024, 1, 31))
    report = build_quality_report(
        [_bar(date(2024, 1, 2))], request, warmup_complete=False
    )
    assert report.grade == "D"
    assert report.decision == "block"
    assert "warmup_insufficient" in report.flags


def test_technical_evidence_applies_required_warmup_before_signals():
    class ShortHistory:
        name = "short-history-review-source"
        capabilities = None

        def fetch_bars(self, request):
            return VendorBarsResult(
                source=self.name,
                bars=[_bar(request.end_date, source=self.name)],
            )

    root = _root("warmup")
    try:
        service = MarketDataService(
            {ShortHistory.name: ShortHistory()},
            snapshot_store=SnapshotStore(root),
            config={"market_data_policy": {"stock_daily": [ShortHistory.name]}},
        )
        result, bundle = build_technical_evidence(
            _request(start=date(2024, 1, 2), end=date(2024, 1, 2)),
            service=service,
        )
        assert result.quality.decision == "block"
        assert "warmup_insufficient" in result.quality.flags
        assert bundle.signals == []
        assert bundle.assessment is None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_runtime_technical_configs_are_loaded_from_versioned_yaml():
    indicators = IndicatorEngine().config
    signals = SignalEngine()
    assert indicators.version == "indicator-config-v1"
    assert indicators.sma_periods == (20, 50, 200)
    assert signals.rule_version == "technical-signal-v1"
    assert signals.rules["weights"]["trend"] == 0.30


def test_per_attempt_timeout_falls_back_without_waiting_for_primary():
    class Slow:
        name = "slow-review-source"
        capabilities = None

        def fetch_bars(self, request):
            time.sleep(1.0)
            return VendorBarsResult(source=self.name, bars=[_bar(request.end_date, source=self.name)])

    class Fast:
        name = "fast-review-source"
        capabilities = None

        def fetch_bars(self, request):
            return VendorBarsResult(source=self.name, bars=[_bar(request.end_date, source=self.name)])

    root = _root("timeout")
    try:
        service = MarketDataService(
            {Slow.name: Slow(), Fast.name: Fast()},
            snapshot_store=SnapshotStore(root),
            config={"market_data_policy": {
                "stock_daily": [Slow.name, Fast.name],
                "max_attempts": 2,
                "per_attempt_timeout_seconds": 0.02,
            }},
        )
        started = time.perf_counter()
        result = service.fetch(_request(start=date(2024, 1, 2), end=date(2024, 1, 2)))
        assert time.perf_counter() - started < 0.6
        assert [attempt.status for attempt in result.attempts] == ["timeout", "success"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_default_circuit_breaker_state_survives_service_recreation():
    source = f"always-fail-{uuid4().hex}"

    class Failing:
        name = source
        capabilities = None

        def fetch_bars(self, request):
            raise RuntimeError("offline")

    root = _root("circuit")
    config = {"market_data_policy": {"stock_daily": [source], "max_attempts": 1}}
    try:
        for _ in range(3):
            MarketDataService(
                {source: Failing()}, snapshot_store=SnapshotStore(root), config=config
            ).fetch(_request())
        result = MarketDataService(
            {source: Failing()}, snapshot_store=SnapshotStore(root), config=config
        ).fetch(_request())
        assert result.attempts[0].status == "circuit_open"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_concurrent_identical_snapshot_writes_are_idempotent(monkeypatch):
    root = _root("snapshot-race")
    request = _request(start=date(2024, 1, 2), end=date(2024, 1, 2))
    result = MarketDataResult(
        request=request,
        bars=[_bar(date(2024, 1, 2))],
        quality=DataQualityReport(grade="B", decision="allow", source_status="PRIMARY_OK"),
    )
    import tradingagents.dataflows.snapshots as snapshots

    real_replace = snapshots.os.replace
    barrier = threading.Barrier(2)

    def racing_replace(source, target):
        barrier.wait(timeout=2)
        return real_replace(source, target)

    monkeypatch.setattr(snapshots.os, "replace", racing_replace)
    try:
        store = SnapshotStore(root)
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: store.save(result), range(2)))
        assert ids[0] == ids[1]
        assert store.load(ids[0]).bars == result.bars
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_quality_summary_fails_when_market_data_gate_blocks():
    llm = type("LLM", (), {"invoke": lambda self, prompt: (_ for _ in ()).throw(AssertionError("LLM must be skipped"))})()
    gate = create_quality_gate(llm, selected_analysts=["market"])
    report = ("完整技术报告。" * 50) + "\n| 项目 | 值 |\n| --- | --- |\n"
    result = gate({
        "trade_date": "2026-05-12",
        "company_of_interest": "600519",
        "market_report": report,
        "market_data_quality": {
            "grade": "D", "decision": "block", "source_status": "CONFLICT", "flags": ["cross_source_conflict"]
        },
    })
    assert result["data_quality_failed"] is True
    assert "未通过 ❌" in result["data_quality_summary"]
    assert "市场数据质量决策为阻断" in result["data_quality_summary"]
