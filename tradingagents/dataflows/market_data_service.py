"""Configuration-driven market-data routing with explicit provenance."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import date, datetime, timezone
from typing import Callable, Iterable, Mapping

from .config import get_config, load_project_versioned_config
from .models import (
    MarketDataRequest,
    MarketDataResult,
    SourceAttempt,
    VendorBarsResult,
)
from .snapshots import SnapshotError, SnapshotNotFound, SnapshotStore
from .validation import build_quality_report, check_cross_source_consistency, merge_bars, validate_bars
from .vendors.base import (
    MarketDataVendor,
    VendorError,
    VendorUnsupportedRequest,
    classify_exception,
)
from .vendors.eastmoney_adapter import EastmoneyAdapter
from .vendors.health import VendorHealthRegistry
from .vendors.mootdx_adapter import MootdxAdapter
from .vendors.sina_adapter import SinaAdapter

logger = logging.getLogger(__name__)


DEFAULT_MARKET_DATA_POLICY = {
    "stock_daily": ["mootdx", "sina"],
    "etf_daily": ["eastmoney", "sina"],
    "index_daily": ["sina"],
    "max_attempts": 2,
    "per_attempt_timeout_seconds": 15,
}

_SHARED_HEALTH_REGISTRY = VendorHealthRegistry()


def _policy_key(request: MarketDataRequest) -> str:
    return f"{request.instrument_type}_daily"


def _expected_last_date(
    request: MarketDataRequest, calendar: Iterable[date] | None
) -> date | None:
    if calendar is None:
        return None
    return max(
        (day for day in calendar if request.start_date <= day <= request.end_date),
        default=None,
    )


class MarketDataService:
    """Fetch normalized bars and return a quality decision with lineage."""

    def __init__(
        self,
        vendors: Mapping[str, MarketDataVendor] | Iterable[MarketDataVendor] | None = None,
        *,
        snapshot_store: SnapshotStore | None = None,
        config: Mapping | None = None,
        health_registry: VendorHealthRegistry | None = None,
        trading_calendar: Iterable[date] | Callable[[MarketDataRequest], Iterable[date]] | None = None,
    ):
        self.config = dict(config or get_config())
        self.vendors = self._normalize_vendors(vendors)
        cache_root = self.config.get("data_cache_dir") or ".market-data-cache"
        self.snapshot_store = snapshot_store or SnapshotStore(cache_root)
        self.health = health_registry or _SHARED_HEALTH_REGISTRY
        self.trading_calendar = trading_calendar
        self.quality_rules = load_project_versioned_config("data_quality_rules_v1.yaml")

    @staticmethod
    def _normalize_vendors(vendors):
        if vendors is None:
            return {
                "mootdx": MootdxAdapter(),
                "sina": SinaAdapter(),
                "eastmoney": EastmoneyAdapter(),
            }
        if isinstance(vendors, Mapping):
            return dict(vendors)
        return {vendor.name: vendor for vendor in vendors}

    def _ordered_names(self, request: MarketDataRequest) -> list[str]:
        policy = dict(DEFAULT_MARKET_DATA_POLICY)
        policy.update(load_project_versioned_config("market_data_policy.yaml"))
        policy.update(self.config.get("market_data_policy", {}))
        configured = policy.get(_policy_key(request), [])
        names = [str(name).strip() for name in configured if str(name).strip()]
        return [name for name in names if name in self.vendors][: int(policy.get("max_attempts", 2))]

    def _policy(self) -> dict:
        policy = dict(DEFAULT_MARKET_DATA_POLICY)
        policy.update(load_project_versioned_config("market_data_policy.yaml"))
        policy.update(self.config.get("market_data_policy", {}))
        return policy

    def _calendar_dates(self, request: MarketDataRequest) -> tuple[date, ...] | None:
        if self.trading_calendar is None:
            return None
        values = self.trading_calendar(request) if callable(self.trading_calendar) else self.trading_calendar
        return tuple(values)

    def _is_current_enough(
        self, last_date: date, request: MarketDataRequest, calendar: tuple[date, ...] | None
    ) -> bool:
        expected = _expected_last_date(request, calendar)
        if expected is not None:
            return last_date >= expected
        max_gap = int(self.quality_rules["max_stale_calendar_days_without_calendar"])
        return (request.end_date - last_date).days < max_gap

    def _fetch_with_timeout(self, vendor: MarketDataVendor, request: MarketDataRequest):
        timeout = float(self._policy().get("per_attempt_timeout_seconds", 15))
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"market-data-{vendor.name}")
        future = executor.submit(vendor.fetch_bars, request)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError as exc:
            future.cancel()
            from .vendors.base import VendorTimeout

            raise VendorTimeout(f"{vendor.name} timed out after {timeout:g}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _make_attempt(
        self,
        source: str,
        started_at: datetime,
        elapsed_ms: int,
        status: str,
        *,
        bars=(),
        error: Exception | None = None,
        code: str | None = None,
    ) -> SourceAttempt:
        bars = list(bars)
        return SourceAttempt(
            source=source,
            started_at=started_at,
            elapsed_ms=elapsed_ms,
            status=status,
            row_count=len(bars),
            first_date=min((bar.trade_date for bar in bars), default=None),
            last_date=max((bar.trade_date for bar in bars), default=None),
            error_code=code or getattr(error, "error_code", None),
            error_summary=str(error)[:240] if error else None,
        )

    def fetch(
        self,
        request: MarketDataRequest,
        *,
        mode: str = "online",
        snapshot_id: str | None = None,
        required_warmup: int | None = None,
    ) -> MarketDataResult:
        if mode not in {"online", "prefer_cache", "offline"}:
            raise ValueError("mode must be online, prefer_cache, or offline")
        if mode == "offline":
            if not snapshot_id:
                raise SnapshotNotFound("offline mode requires snapshot_id")
            result = self.snapshot_store.load(snapshot_id)
            if result.request != request:
                raise SnapshotError("snapshot request does not match requested data")
            return result
        if mode == "prefer_cache":
            cached = self.snapshot_store.find_by_request(request)
            if cached is not None:
                return cached

        attempts: list[SourceAttempt] = []
        candidates: list[tuple[VendorBarsResult, object]] = []
        raw_responses = {}
        calendar = self._calendar_dates(request)
        for source in self._ordered_names(request):
            vendor = self.vendors[source]
            if not self.health.allow(source):
                attempts.append(
                    self._make_attempt(
                        source,
                        datetime.now(timezone.utc),
                        0,
                        "circuit_open",
                        error=RuntimeError("vendor circuit is open"),
                        code="circuit_open",
                    )
                )
                continue
            started = datetime.now(timezone.utc)
            start_clock = time.perf_counter()
            try:
                capabilities = getattr(vendor, "capabilities", None)
                if capabilities and (
                    request.instrument_type not in capabilities.instrument_types
                    or request.frequency not in capabilities.frequencies
                    or request.adjustment not in capabilities.adjustments
                ):
                    raise VendorUnsupportedRequest(f"{source} does not support this request")
                result = self._fetch_with_timeout(vendor, request)
                if not isinstance(result, VendorBarsResult):
                    raise VendorError(f"{source} returned an invalid structured result", error_code="schema_error")
                checked = validate_bars(result.bars, request, calendar=calendar)
                raw_responses[source] = result.raw_response
                if not checked.bars:
                    raise VendorError(f"{source} returned no valid bars", error_code="empty")
                last_date = max(bar.trade_date for bar in checked.bars)
                current_enough = self._is_current_enough(last_date, request, calendar)
                attempt_status = "success" if current_enough else "stale"
                attempts.append(
                    self._make_attempt(
                        source,
                        started,
                        int((time.perf_counter() - start_clock) * 1000),
                        attempt_status,
                        bars=checked.bars,
                    )
                )
                self.health.record_success(source)
                candidates.append((result, checked))
                # A complete current source is sufficient; a second source is
                # still used when the result is stale so the service can recover.
                if current_enough:
                    break
            except Exception as exc:
                mapped = classify_exception(exc)
                self.health.record_failure(source)
                attempts.append(
                    self._make_attempt(
                        source,
                        started,
                        int((time.perf_counter() - start_clock) * 1000),
                        mapped.status,
                        error=mapped,
                    )
                )
                logger.info(
                    json.dumps(
                        {"event": "market_data_attempt", "source": source, "status": mapped.status, "error_code": mapped.error_code},
                        ensure_ascii=False,
                    )
                )

        if not candidates:
            quality = build_quality_report(
                [], request, attempts=attempts, source_status="UNAVAILABLE", calendar=calendar,
                warmup_complete=required_warmup is None,
            )
            result = MarketDataResult(request=request, attempts=attempts, quality=quality)
            return self._snapshot(result, raw_responses)

        selected = candidates[0]
        source_status = "PRIMARY_OK"
        all_conflicts = []
        if len(candidates) > 1:
            conflicts = check_cross_source_consistency(candidates[0][0].bars, candidates[1][0].bars)
            all_conflicts.extend(conflicts)
            merged = merge_bars(candidates[0][1].bars, candidates[1][1].bars, conflicts=conflicts)
            if conflicts:
                source_status = "CONFLICT"
            elif merged.flags and "merged_sources" in merged.flags:
                selected = (candidates[0][0], type("_Checked", (), {"bars": merged.bars, "flags": merged.flags, "missing_dates": [], "invalid_rows": 0})())
                source_status = "MERGED"
            else:
                selected = candidates[-1]
                source_status = "FALLBACK_OK"
        elif attempts and attempts[0].status == "stale":
            source_status = "STALE"
        elif attempts and attempts[0].status != "success":
            source_status = "FALLBACK_OK"
        elif attempts and attempts[0].source != self._ordered_names(request)[0]:
            source_status = "FALLBACK_OK"

        selected_bars = selected[1].bars
        quality = build_quality_report(
            selected_bars,
            request,
            attempts=attempts,
            source_status=source_status,
            conflicts=all_conflicts,
            single_source_unverified=len(candidates) < 2,
            calendar=calendar,
            warmup_complete=(required_warmup is None or len(selected_bars) >= required_warmup),
        )
        result = MarketDataResult(
            request=request,
            bars=selected_bars,
            attempts=attempts,
            quality=quality,
            raw_responses=raw_responses,
        )
        logger.info(
            json.dumps(
                {"event": "market_data_result", "symbol": request.symbol, "source_status": source_status, "quality": quality.grade, "decision": quality.decision},
                ensure_ascii=False,
            )
        )
        return self._snapshot(result, raw_responses)

    fetch_bars = fetch

    def _snapshot(self, result: MarketDataResult, raw_responses: dict) -> MarketDataResult:
        try:
            snapshot_id = self.snapshot_store.save(result, raw_responses=raw_responses)
        except (OSError, SnapshotError) as exc:
            # A data result remains useful, but the missing snapshot must be
            # visible to callers rather than silently treated as reproducible.
            result.quality.flags.append("snapshot_write_failed")
            logger.warning("market data snapshot write failed: %s", exc)
        else:
            result.snapshot_id = snapshot_id
        return result


def make_market_data_request(**kwargs) -> MarketDataRequest:
    """Convenience constructor kept in one place for CLI and tests."""
    return MarketDataRequest.model_validate(kwargs)


def build_technical_evidence(
    request: MarketDataRequest,
    *,
    mode: str = "online",
    snapshot_id: str | None = None,
    service: MarketDataService | None = None,
    display_start: date | None = None,
):
    """Fetch frozen bars and build the complete deterministic evidence bundle.

    This is the application boundary used by the migrated market analyst. It
    keeps network access in ``MarketDataService`` and leaves indicator/signal
    code pure and reproducible.
    """
    from tradingagents.technical.evidence import build_evidence_bundle
    from tradingagents.technical.indicators import IndicatorEngine
    from tradingagents.technical.signals import SignalEngine

    service = service or MarketDataService()
    indicator_engine = IndicatorEngine()
    result = service.fetch(
        request,
        mode=mode,
        snapshot_id=snapshot_id,
        required_warmup=indicator_engine.config.required_warmup(),
    )
    if result.quality.decision == "block" or not result.bars:
        bundle = build_evidence_bundle(result, display_start=display_start)
        return result, bundle
    frame = indicator_engine.calculate_frame(result.bars)
    evaluation = SignalEngine(indicator_engine.config).run(
        frame,
        quality_grade=result.quality.grade,
        snapshot_id=result.snapshot_id or "",
    )
    bundle = build_evidence_bundle(
        result,
        indicator_frame=frame,
        signals=evaluation.signals,
        assessment=evaluation.assessment,
        display_start=display_start,
    )
    return result, bundle


def build_product_technical_evidence(
    subject_request: MarketDataRequest,
    *,
    reference_request: MarketDataRequest | None = None,
    instrument_profile: dict | None = None,
    analysis_product: str = "a_share_stock",
    mode: str = "online",
    service: MarketDataService | None = None,
    subject_snapshot_id: str | None = None,
    reference_snapshot_id: str | None = None,
    unavailable_capabilities: dict[str, str] | None = None,
):
    """Fetch a v2 multi-series bundle and construct its evidence package."""

    from tradingagents.dataflows.analysis_bundle import fetch_analysis_market_data_bundle
    from tradingagents.technical.product_evidence import build_product_evidence_bundle
    from tradingagents.technical.products import product_required_warmup

    subject_warmup = product_required_warmup(analysis_product)
    reference_warmup = product_required_warmup("index") if reference_request else None
    bundle = fetch_analysis_market_data_bundle(
        subject_request,
        reference_request=reference_request,
        instrument_profile=instrument_profile,
        analysis_product=analysis_product,
        service=service,
        mode=mode,
        subject_snapshot_id=subject_snapshot_id,
        reference_snapshot_id=reference_snapshot_id,
        subject_required_warmup=subject_warmup,
        reference_required_warmup=reference_warmup,
    )
    evidence = build_product_evidence_bundle(
        bundle,
        unavailable_capabilities=unavailable_capabilities,
    )
    return bundle, evidence
