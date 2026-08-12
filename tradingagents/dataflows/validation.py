"""Rule-based market-data validation and quality grading.

Validation is intentionally fail-closed for hard semantic errors.  It never
repairs an OHLC value; invalid rows are omitted only when the caller explicitly
accepts the returned invalid-row count and the quality decision remains safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from .models import (
    DataConflict,
    DataQualityReport,
    MarketDataRequest,
    NormalizedBar,
    SourceAttempt,
)


@dataclass
class BarValidationResult:
    bars: list[NormalizedBar] = field(default_factory=list)
    invalid_rows: int = 0
    flags: list[str] = field(default_factory=list)
    duplicate_dates: list[date] = field(default_factory=list)
    missing_dates: list[date] = field(default_factory=list)


@dataclass
class MergeResult:
    bars: list[NormalizedBar] = field(default_factory=list)
    conflicts: list[DataConflict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def _as_bar(value: NormalizedBar | Mapping) -> NormalizedBar:
    if isinstance(value, NormalizedBar):
        return value
    return NormalizedBar.model_validate(value)


def _business_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def expected_trade_dates(
    start: date,
    end: date,
    *,
    calendar: Iterable[date] | None = None,
) -> list[date]:
    """Return the supplied exchange calendar, or a conservative weekday set."""
    if calendar is not None:
        return sorted({d for d in calendar if start <= d <= end})
    return _business_days(start, end)


def validate_bars(
    bars: Sequence[NormalizedBar | Mapping],
    request: MarketDataRequest | None = None,
    *,
    calendar: Iterable[date] | None = None,
) -> BarValidationResult:
    result = BarValidationResult()
    seen: set[date] = set()
    raw_bars: list[NormalizedBar] = []
    for raw in bars:
        try:
            bar = _as_bar(raw)
            if bar.trade_date in seen:
                result.invalid_rows += 1
                result.duplicate_dates.append(bar.trade_date)
                continue
            if not (bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high):
                result.invalid_rows += 1
                result.flags.append(f"invalid_ohlc:{bar.trade_date.isoformat()}")
                continue
            if any(v <= 0 for v in (bar.open, bar.high, bar.low, bar.close)):
                result.invalid_rows += 1
                result.flags.append(f"non_positive_ohlc:{bar.trade_date.isoformat()}")
                continue
            if request is not None:
                if bar.trade_date < request.start_date or bar.trade_date > request.end_date:
                    result.invalid_rows += 1
                    result.flags.append(f"date_outside_request:{bar.trade_date.isoformat()}")
                    continue
                if bar.symbol != request.symbol:
                    result.invalid_rows += 1
                    result.flags.append(f"symbol_mismatch:{bar.trade_date.isoformat()}")
                    continue
                if bar.adjustment != request.adjustment:
                    result.flags.append("adjustment_mismatch")
            seen.add(bar.trade_date)
            raw_bars.append(bar)
        except Exception as exc:
            result.invalid_rows += 1
            result.flags.append(f"schema_error:{type(exc).__name__}")

    result.bars = sorted(raw_bars, key=lambda item: item.trade_date)
    if request is not None and result.bars:
        expected = set(expected_trade_dates(request.start_date, request.end_date, calendar=calendar))
        actual = {bar.trade_date for bar in result.bars}
        result.missing_dates = sorted(expected - actual)
        if result.missing_dates:
            result.flags.append("missing_trade_dates")
    if result.duplicate_dates:
        result.flags.append("duplicate_dates")
    return result


def _relative_difference(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None:
        return None
    denominator = max(abs(a), abs(b), Decimal("0.000001"))
    return abs(a - b) / denominator


def check_cross_source_consistency(
    left: Sequence[NormalizedBar],
    right: Sequence[NormalizedBar],
    *,
    sample_size: int = 5,
    price_tolerance: Decimal | float = Decimal("0.005"),
    volume_tolerance: Decimal | float = Decimal("0.10"),
) -> list[DataConflict]:
    """Compare overlapping bars and return every material conflict."""
    left_by_date = {bar.trade_date: bar for bar in left}
    right_by_date = {bar.trade_date: bar for bar in right}
    overlap = sorted(left_by_date.keys() & right_by_date.keys())[-sample_size:]
    conflicts: list[DataConflict] = []
    price_tolerance = Decimal(str(price_tolerance))
    volume_tolerance = Decimal(str(volume_tolerance))
    for trade_date in overlap:
        a, b = left_by_date[trade_date], right_by_date[trade_date]
        fields: list[str] = []
        values: dict[str, str] = {}
        for field_name in ("open", "high", "low", "close"):
            av, bv = getattr(a, field_name), getattr(b, field_name)
            if (_relative_difference(av, bv) or Decimal(0)) > price_tolerance:
                fields.append(field_name)
                values[field_name] = f"{av} vs {bv}"
        if a.volume is not None and b.volume is not None:
            if (_relative_difference(a.volume, b.volume) or Decimal(0)) > volume_tolerance:
                fields.append("volume")
                values["volume"] = f"{a.volume} vs {b.volume}"
        if fields:
            conflicts.append(
                DataConflict(
                    trade_date=trade_date,
                    source_a=a.source,
                    source_b=b.source,
                    fields=fields,
                    values=values,
                )
            )
    return conflicts


def merge_bars(
    primary: Sequence[NormalizedBar],
    supplement: Sequence[NormalizedBar],
    *,
    conflicts: Sequence[DataConflict] | None = None,
) -> MergeResult:
    """Merge by date without silently overwriting an overlapping bar."""
    found_conflicts = list(conflicts or check_cross_source_consistency(primary, supplement))
    conflict_dates = {item.trade_date for item in found_conflicts}
    by_date = {bar.trade_date: bar for bar in primary}
    flags: list[str] = []
    for bar in supplement:
        existing = by_date.get(bar.trade_date)
        if existing is None:
            by_date[bar.trade_date] = bar
        elif bar.trade_date in conflict_dates:
            flags.append(f"conflict:{bar.trade_date.isoformat()}")
        # Matching overlap stays with the primary and is not silently changed.
    if supplement and any(bar.trade_date not in {b.trade_date for b in primary} for bar in supplement):
        flags.append("merged_sources")
    return MergeResult(sorted(by_date.values(), key=lambda item: item.trade_date), found_conflicts, flags)


def _last_expected_date(request: MarketDataRequest) -> date:
    expected = request.end_date
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    return expected


def build_quality_report(
    bars: Sequence[NormalizedBar],
    request: MarketDataRequest,
    *,
    attempts: Sequence[SourceAttempt] = (),
    source_status: str = "PRIMARY_OK",
    conflicts: Sequence[DataConflict] = (),
    validation: BarValidationResult | None = None,
    calendar: Iterable[date] | None = None,
    single_source_unverified: bool = True,
    warmup_complete: bool = True,
) -> DataQualityReport:
    """Apply hard-block-first quality rules to one normalized dataset."""
    checked = validation or validate_bars(bars, request, calendar=calendar)
    clean_bars = checked.bars
    flags = list(dict.fromkeys(checked.flags))
    conflicts = list(conflicts)
    if single_source_unverified and not conflicts:
        flags.append("single_source_unverified")
    if not warmup_complete:
        flags.append("warmup_insufficient")
    last_date = max((bar.trade_date for bar in clean_bars), default=None)
    stale_days = 0
    if last_date is not None:
        stale_days = max(0, (_last_expected_date(request) - last_date).days)
        if stale_days >= 1:
            flags.append("stale")
    else:
        flags.append("no_valid_bars")
    if request.adjustment and any(bar.adjustment == "unknown" for bar in clean_bars):
        flags.append("adjustment_unknown")
    if conflicts:
        flags.append("cross_source_conflict")
    if checked.invalid_rows:
        flags.append("invalid_rows")

    completeness = 0.0
    if request.end_date >= request.start_date:
        expected_count = max(1, len(expected_trade_dates(request.start_date, request.end_date, calendar=calendar)))
        completeness = min(1.0, len(clean_bars) / expected_count)
    freshness = 1.0 if last_date is None else (1.0 if stale_days == 0 else max(0.0, 1.0 - stale_days / 5))
    consistency = 0.0 if conflicts else 1.0
    semantics = 0.0 if "adjustment_unknown" in flags or "schema_error" in " ".join(flags) else 1.0
    hard_block = bool(conflicts or not clean_bars or "schema_error" in " ".join(flags))
    severe_invalid = checked.invalid_rows > max(1, len(clean_bars) // 5)
    if severe_invalid:
        hard_block = True
    if hard_block:
        grade = "F" if not clean_bars or "no_valid_bars" in flags or "schema_error" in " ".join(flags) else "D"
        decision = "block"
    elif "adjustment_unknown" in flags or not warmup_complete:
        grade, decision = "D", "block"
    elif "stale" in flags or checked.missing_dates or source_status in {"MERGED", "PARTIAL"}:
        grade, decision = "C", "observe_only"
    elif source_status == "FALLBACK_OK" or "single_source_unverified" in flags:
        grade, decision = "B", "allow"
    else:
        grade, decision = "A", "allow"
    lineage = ", ".join(
        f"{attempt.source}:{attempt.status}:{attempt.row_count} rows"
        for attempt in attempts
    )
    return DataQualityReport(
        grade=grade,
        decision=decision,
        source_status=source_status,
        completeness_score=completeness,
        freshness_score=freshness,
        consistency_score=consistency,
        semantics_score=semantics,
        flags=list(dict.fromkeys(flags)),
        missing_dates=checked.missing_dates,
        conflicts=conflicts,
        lineage_summary=lineage,
        invalid_rows=checked.invalid_rows,
        total_rows=len(bars),
        last_trade_date=last_date,
    )


def validate_dataset(*args, **kwargs) -> DataQualityReport:
    """Compatibility name used by callers migrating from ad-hoc checks."""
    return build_quality_report(*args, **kwargs)


def validate_market_data(*args, **kwargs) -> DataQualityReport:
    return build_quality_report(*args, **kwargs)

