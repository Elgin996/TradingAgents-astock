"""Independent multi-series market-data bundles and alignment gates."""

from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import Any, Iterable

from .market_data_service import MarketDataService
from .models import (
    AnalysisMarketDataBundle,
    MarketDataRequest,
    MarketDataResult,
    SeriesAlignmentReport,
)


ALIGNMENT_RULE_VERSION = "series-alignment-v1"
BUNDLE_RULE_VERSION = "analysis-bundle-v1"


def _dates(result: MarketDataResult | None) -> set[date]:
    return {bar.trade_date for bar in (result.bars if result else [])}


def _series_variant(result: MarketDataResult, explicit: str | None, *, reference: bool) -> str:
    if explicit:
        return explicit
    if result.request.series_variant != "unknown":
        return result.request.series_variant
    if not reference and result.request.instrument_type in {"stock", "etf"}:
        return "market_price"
    return "unknown"


def align_series(
    subject: MarketDataResult,
    reference: MarketDataResult | None,
    *,
    min_common_observations: int = 20,
    min_coverage: float = 0.8,
    subject_series_variant: str | None = None,
    reference_series_variant: str | None = None,
) -> SeriesAlignmentReport:
    """Compare real dates and series semantics without filling observations."""

    subject_dates = _dates(subject)
    reference_dates = _dates(reference)
    common = subject_dates & reference_dates
    subject_only = sorted(subject_dates - common)
    reference_only = sorted(reference_dates - common)
    subject_variant = _series_variant(subject, subject_series_variant, reference=False)
    reference_variant = (
        _series_variant(reference, reference_series_variant, reference=True)
        if reference is not None
        else "unknown"
    )
    flags: list[str] = []
    if reference is None:
        flags.append("reference_unavailable")
    if not common:
        flags.append("no_common_dates")
    if len(common) < min_common_observations:
        flags.append("insufficient_common_observations")
    coverage = (
        min(
            len(common) / len(subject_dates) if subject_dates else 0.0,
            len(common) / len(reference_dates) if reference_dates else 0.0,
        )
        if reference is not None
        else 0.0
    )
    if reference is not None and coverage < min_coverage:
        flags.append("coverage_below_threshold")
    if reference is not None and reference_variant == "unknown":
        flags.append("reference_series_variant_unknown")
    if reference is not None and subject_variant == "unknown":
        flags.append("subject_series_variant_unknown")
    if reference is not None and reference.quality.decision == "block":
        flags.append("reference_quality_block")
    if subject.quality.decision == "block":
        flags.append("subject_quality_block")
    if reference is not None and subject.request.currency != reference.request.currency:
        flags.append("currency_mismatch")
    if reference is not None and subject.request.timezone != reference.request.timezone:
        flags.append("timezone_mismatch")
    if reference is not None and subject.request.frequency != reference.request.frequency:
        flags.append("frequency_mismatch")
    if reference is not None and subject.request.adjustment != reference.request.adjustment:
        flags.append("adjustment_mismatch")

    if reference is None or not common or len(common) < min_common_observations:
        decision = "block"
    elif any(
        flag.endswith("unknown")
        or flag
        in {
            "currency_mismatch",
            "timezone_mismatch",
            "frequency_mismatch",
            "adjustment_mismatch",
        }
        for flag in flags
    ):
        decision = "block"
    elif subject.quality.decision == "block" or reference.quality.decision == "block":
        decision = "block"
    elif subject.quality.decision == "observe_only" or reference.quality.decision == "observe_only":
        decision = "observe_only"
    elif coverage < min_coverage:
        decision = "block"
    else:
        decision = "allow"
    common_dates = sorted(common)
    return SeriesAlignmentReport(
        start_date=common_dates[0] if common_dates else None,
        end_date=common_dates[-1] if common_dates else None,
        subject_observations=len(subject_dates),
        reference_observations=len(reference_dates),
        common_observations=len(common),
        common_coverage=max(0.0, min(1.0, coverage)),
        subject_only_dates=subject_only,
        reference_only_dates=reference_only,
        subject_series_variant=subject_variant,
        reference_series_variant=reference_variant,
        decision=decision,
        flags=list(dict.fromkeys(flags)),
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def build_bundle_snapshot_id(
    *,
    instrument_profile: dict[str, Any] | None,
    subject_snapshot_id: str | None,
    reference_snapshot_id: str | None,
    alignment: SeriesAlignmentReport | None,
    analysis_product: str,
    catalog_version: str = "index-catalog-v2",
    product_rules_version: str = "technical-products-v2",
    alignment_rules_version: str = ALIGNMENT_RULE_VERSION,
) -> str:
    payload = {
        "instrument_profile": instrument_profile or {},
        "subject_snapshot_id": subject_snapshot_id or "",
        "reference_snapshot_id": reference_snapshot_id or "",
        "alignment": alignment.model_dump(mode="json") if alignment else None,
        "analysis_product": analysis_product,
        "catalog_version": catalog_version,
        "product_rules_version": product_rules_version,
        "alignment_rules_version": alignment_rules_version,
    }
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


def _overall_decision(
    subject: MarketDataResult,
    reference: MarketDataResult | None,
    alignment: SeriesAlignmentReport | None,
    analysis_product: str,
) -> str:
    if subject.quality.decision == "block":
        return "block"
    if subject.quality.decision == "observe_only":
        return "observe_only"
    if analysis_product == "passive_equity_etf" and (
        reference is None or alignment is None or alignment.decision != "allow"
    ):
        return "observe_only"
    if (
        analysis_product == "passive_equity_etf"
        and alignment is not None
        and alignment.decision != "allow"
        and reference is not None
    ):
        return "observe_only"
    return "allow"


def build_analysis_market_data_bundle(
    subject: MarketDataResult,
    reference: MarketDataResult | None = None,
    *,
    instrument_profile: dict[str, Any] | None = None,
    analysis_product: str = "a_share_stock",
    min_common_observations: int = 20,
    min_coverage: float = 0.8,
    catalog_version: str = "index-catalog-v2",
    product_rules_version: str = "technical-products-v2",
) -> AnalysisMarketDataBundle:
    alignment = (
        align_series(
            subject,
            reference,
            min_common_observations=min_common_observations,
            min_coverage=min_coverage,
        )
        if reference is not None
        else None
    )
    flags = list(alignment.flags if alignment else [])
    if reference is None and analysis_product == "passive_equity_etf":
        flags.append("passive_tracking_reference_missing")
    overall = _overall_decision(subject, reference, alignment, analysis_product)
    snapshot_id = build_bundle_snapshot_id(
        instrument_profile=instrument_profile,
        subject_snapshot_id=subject.snapshot_id,
        reference_snapshot_id=reference.snapshot_id if reference else None,
        alignment=alignment,
        analysis_product=analysis_product,
        catalog_version=catalog_version,
        product_rules_version=product_rules_version,
    )
    return AnalysisMarketDataBundle(
        subject=subject,
        reference=reference,
        alignment=alignment,
        bundle_snapshot_id=snapshot_id,
        overall_decision=overall,
        flags=list(dict.fromkeys(flags)),
        analysis_product=analysis_product,
        instrument_profile=instrument_profile or {},
        versions={
            "bundle": BUNDLE_RULE_VERSION,
            "alignment": ALIGNMENT_RULE_VERSION,
            "catalog": catalog_version,
            "product_rules": product_rules_version,
        },
    )


def fetch_analysis_market_data_bundle(
    subject_request: MarketDataRequest,
    *,
    reference_request: MarketDataRequest | None = None,
    instrument_profile: dict[str, Any] | None = None,
    analysis_product: str = "a_share_stock",
    service: MarketDataService | None = None,
    mode: str = "online",
    subject_snapshot_id: str | None = None,
    reference_snapshot_id: str | None = None,
    subject_required_warmup: int | None = None,
    reference_required_warmup: int | None = None,
    min_common_observations: int = 20,
    min_coverage: float = 0.8,
) -> AnalysisMarketDataBundle:
    """Fetch subject and reference independently, then build one bundle."""

    service = service or MarketDataService()
    subject = service.fetch(
        subject_request,
        mode=mode,
        snapshot_id=subject_snapshot_id,
        required_warmup=subject_required_warmup,
    )
    reference = None
    if reference_request is not None:
        reference = service.fetch(
            reference_request,
            mode=mode,
            snapshot_id=reference_snapshot_id,
            required_warmup=reference_required_warmup,
        )
    return build_analysis_market_data_bundle(
        subject,
        reference,
        instrument_profile=instrument_profile,
        analysis_product=analysis_product,
        min_common_observations=min_common_observations,
        min_coverage=min_coverage,
    )


def rebuild_bundle_snapshot(bundle: AnalysisMarketDataBundle) -> str:
    """Recompute the content-addressed bundle ID from offline bundle facts."""

    return build_bundle_snapshot_id(
        instrument_profile=bundle.instrument_profile,
        subject_snapshot_id=bundle.subject.snapshot_id,
        reference_snapshot_id=bundle.reference.snapshot_id if bundle.reference else None,
        alignment=bundle.alignment,
        analysis_product=bundle.analysis_product,
        catalog_version=bundle.versions.get("catalog", "index-catalog-v2"),
        product_rules_version=bundle.versions.get("product_rules", "technical-products-v2"),
        alignment_rules_version=bundle.versions.get("alignment", ALIGNMENT_RULE_VERSION),
    )
