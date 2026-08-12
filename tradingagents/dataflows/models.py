"""Structured contracts for market-data requests, provenance, and quality.

The legacy data-flow functions in this project return markdown/CSV strings
because they are exposed as LangChain tools.  These models are the internal
contract used by the reliable path: vendors return structured data, validators
return structured quality decisions, and a compatibility facade may render the
result for an old tool caller.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Adjustment = Literal["raw", "forward", "backward", "unknown"]
SeriesVariant = Literal[
    "market_price",
    "price",
    "total_return",
    "net_total_return",
    "unknown",
]
QualityGrade = Literal["A", "B", "C", "D", "F"]
QualityDecision = Literal["allow", "observe_only", "block"]
SourceAttemptStatus = Literal[
    "success",
    "timeout",
    "rate_limited",
    "network_error",
    "schema_error",
    "empty",
    "stale",
    "conflict",
    "unsupported",
    "circuit_open",
]


class ContractModel(BaseModel):
    """Common model settings used for deterministic serialization."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ReferenceInstrument(ContractModel):
    """A provider-qualified, auditable reference relationship.

    ``code`` is intentionally allowed to be empty for a frozen but unresolved
    relationship.  That state is represented by ``status=missing`` rather
    than by guessing a code from a product name.
    """

    role: Literal["tracking_index", "benchmark"]
    code: str = ""
    name: str = ""
    provider: str = ""
    series_variant: SeriesVariant = "unknown"
    source: str = ""
    status: Literal["verified", "user_supplied", "ambiguous", "missing"] = "missing"
    verified_at: str = ""
    instrument_id: str | None = None

    @model_validator(mode="after")
    def validate_resolved_identity(self) -> "ReferenceInstrument":
        if self.status in {"verified", "user_supplied"} and (
            not self.code.strip() or not self.provider.strip()
        ):
            raise ValueError("resolved reference instruments require code and provider")
        return self


class MarketDataRequest(ContractModel):
    symbol: str = Field(min_length=1)
    exchange: Literal["SSE", "SZSE", "BSE"]
    instrument_type: Literal["stock", "etf", "index"]
    start_date: date
    end_date: date
    frequency: Literal["1d"] = "1d"
    adjustment: Literal["raw", "forward", "backward"]
    as_of: datetime
    series_variant: SeriesVariant = "unknown"
    currency: str = "CNY"
    timezone: str = "Asia/Shanghai"

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("symbol must not be empty")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "MarketDataRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if self.end_date > self.as_of.date():
            raise ValueError("end_date must not be later than as_of")
        return self


class NormalizedBar(ContractModel):
    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    amount: Decimal | None = None
    adjustment: Adjustment
    source: str
    source_symbol: str
    retrieved_at: datetime
    flags: set[str] = Field(default_factory=set)

    @field_validator("open", "high", "low", "close", "volume", "amount")
    @classmethod
    def validate_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if not isfinite(float(value)):
            raise ValueError("OHLCV values must be finite")
        return value

    @field_validator("volume", "amount")
    @classmethod
    def validate_non_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("volume and amount must not be negative")
        return value


class SourceAttempt(ContractModel):
    source: str
    started_at: datetime
    elapsed_ms: int = Field(default=0, ge=0)
    status: SourceAttemptStatus
    row_count: int = Field(default=0, ge=0)
    first_date: date | None = None
    last_date: date | None = None
    error_code: str | None = None
    error_summary: str | None = None


class DataConflict(ContractModel):
    trade_date: date
    source_a: str
    source_b: str
    fields: list[str] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)
    reason: str = "cross-source values exceed tolerance"


class DataQualityReport(ContractModel):
    grade: QualityGrade = "F"
    decision: QualityDecision = "block"
    source_status: str = "UNAVAILABLE"
    completeness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    freshness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    consistency_score: float = Field(default=0.0, ge=0.0, le=1.0)
    semantics_score: float = Field(default=0.0, ge=0.0, le=1.0)
    flags: list[str] = Field(default_factory=list)
    missing_dates: list[date] = Field(default_factory=list)
    conflicts: list[DataConflict] = Field(default_factory=list)
    lineage_summary: str = ""
    invalid_rows: int = Field(default=0, ge=0)
    total_rows: int = Field(default=0, ge=0)
    last_trade_date: date | None = None


class MarketDataResult(ContractModel):
    request: MarketDataRequest
    bars: list[NormalizedBar] = Field(default_factory=list)
    attempts: list[SourceAttempt] = Field(default_factory=list)
    quality: DataQualityReport = Field(default_factory=DataQualityReport)
    snapshot_id: str | None = None
    raw_responses: dict[str, Any] = Field(default_factory=dict)


class SeriesAlignmentReport(ContractModel):
    """Date and semantic alignment facts for two independently fetched series."""

    start_date: date | None = None
    end_date: date | None = None
    subject_observations: int = Field(default=0, ge=0)
    reference_observations: int = Field(default=0, ge=0)
    common_observations: int = Field(default=0, ge=0)
    common_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    subject_only_dates: list[date] = Field(default_factory=list)
    reference_only_dates: list[date] = Field(default_factory=list)
    subject_series_variant: str = "unknown"
    reference_series_variant: str = "unknown"
    decision: QualityDecision = "block"
    flags: list[str] = Field(default_factory=list)


class AnalysisMarketDataBundle(ContractModel):
    """Independent subject/reference data plus their reproducible alignment."""

    subject: MarketDataResult
    reference: MarketDataResult | None = None
    alignment: SeriesAlignmentReport | None = None
    bundle_snapshot_id: str
    overall_decision: QualityDecision = "block"
    flags: list[str] = Field(default_factory=list)
    analysis_product: str = "a_share_stock"
    instrument_profile: dict[str, Any] = Field(default_factory=dict)
    versions: dict[str, str] = Field(default_factory=dict)


class RelativeMetric(ContractModel):
    """One cross-series metric with explicit semantics and provenance."""

    metric_id: str
    value: float | None = None
    window: int | None = None
    as_of: date
    subject_snapshot_id: str
    reference_snapshot_id: str
    common_observations: int = Field(default=0, ge=0)
    status: Literal["ok", "insufficient", "blocked"] = "blocked"
    semantics: str
    rule_version: str


class VendorCapabilities(ContractModel):
    instrument_types: set[str] = Field(default_factory=lambda: {"stock"})
    frequencies: set[str] = Field(default_factory=lambda: {"1d"})
    adjustments: set[str] = Field(default_factory=lambda: {"unknown"})
    provides_amount: bool = False


class VendorBarsResult(ContractModel):
    source: str
    bars: list[NormalizedBar] = Field(default_factory=list)
    raw_response: Any | None = None
    source_status: str = "PRIMARY_OK"
    adjustment: Adjustment = "unknown"
    unit_flags: set[str] = Field(default_factory=set)


class IndicatorValue(ContractModel):
    name: str
    value: float | None
    trade_date: date
    parameters: dict[str, int | float | str] = Field(default_factory=dict)
    warmup_complete: bool = False
    engine_version: str


class TechnicalSignal(ContractModel):
    signal_id: str
    category: Literal["trend", "momentum", "volatility", "volume", "level"]
    direction: Literal["bullish", "bearish", "neutral", "unavailable"]
    strength: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    observed_at: date
    inputs: dict[str, float | str | None] = Field(default_factory=dict)
    rule_version: str
    explanation_key: str


class TechnicalAssessment(ContractModel):
    stance: Literal["bullish", "bearish", "neutral", "mixed", "unavailable"]
    score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    decision: QualityDecision
    supporting_signal_ids: list[str] = Field(default_factory=list)
    conflicting_signal_ids: list[str] = Field(default_factory=list)
    data_quality_grade: QualityGrade
    snapshot_id: str = ""
    indicator_config_version: str
    signal_rule_version: str


class ReportValidationResult(ContractModel):
    valid: bool
    issues: list[str] = Field(default_factory=list)
    cited_evidence_ids: list[str] = Field(default_factory=list)
