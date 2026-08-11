"""Resolve the capabilities that are valid for a frozen instrument profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence


ETF_PHASE_ONE_CAPABILITIES = frozenset(
    {
        "price_history",
        "technical_indicators",
        "liquidity_metrics",
        "fund_profile",
        "shares_and_aum",
        "index_news_policy",
    }
)
# Stage 3 subset deliverable with Stage-1 data only (no IOPV / weights / TR).
ETF_PHASE_THREE_CAPABILITIES = frozenset(
    {
        "peer_comparison",
    }
)
ETF_ENABLED_CAPABILITIES = ETF_PHASE_ONE_CAPABILITIES | ETF_PHASE_THREE_CAPABILITIES
PHASE_CLOSED_CAPABILITIES = {
    "nav_iopv": "阶段 1.5 已关闭：无稳定、可审计的 IOPV 数据源",
    "premium_discount": "阶段 1.5 已关闭：无法保证价格与 IOPV 同时点可比",
    "index_exposure": "阶段 2 已关闭：无许可清晰的指数权重来源",
    "tracking_quality": "阶段 2 已关闭：无稳定指数全收益序列",
    "pcf": "阶段 2 已关闭：无公共、稳定的 PCF 申赎清单来源",
}

# Analyst nodes and the minimum capabilities that keep them in the run.
# When a required capability is removed at probe time, the analyst/report
# section/progress stage must disappear instead of running empty tool loops.
ETF_ANALYST_REQUIRED_CAPABILITIES: dict[str, frozenset[str]] = {
    "market": frozenset({"price_history", "technical_indicators"}),
    "etf_liquidity": frozenset({"liquidity_metrics"}),
    "etf_structure": frozenset({"fund_profile"}),
    "etf_index_news": frozenset({"index_news_policy"}),
    "etf_compare": frozenset({"peer_comparison"}),
}

ETF_REPORT_FIELD_CAPABILITIES: dict[str, frozenset[str]] = {
    "market_report": frozenset({"price_history", "technical_indicators"}),
    "etf_liquidity_report": frozenset({"liquidity_metrics"}),
    "etf_profile_report": frozenset({"fund_profile"}),
    "etf_index_news_report": frozenset({"index_news_policy"}),
    "etf_compare_report": frozenset({"peer_comparison"}),
}


@dataclass(frozen=True)
class AnalysisCapabilities:
    """Enabled capabilities plus auditable reasons for omitted capabilities."""

    enabled: frozenset[str]
    unavailable: dict[str, str]

    def to_list(self) -> list[str]:
        return sorted(self.enabled)

    def enables(self, required: Iterable[str]) -> bool:
        return set(required).issubset(self.enabled)

    @classmethod
    def for_instrument(
        cls,
        instrument_profile: dict[str, Any] | None,
        analysis_mode: str,
        unavailable: dict[str, str] | None = None,
    ) -> "AnalysisCapabilities":
        if analysis_mode != "etf":
            return cls(frozenset(), {})
        if not instrument_profile or instrument_profile.get("security_type") != "etf":
            raise ValueError("ETF analysis requires a frozen ETF instrument profile")
        unavailable = {**PHASE_CLOSED_CAPABILITIES, **(unavailable or {})}
        return cls(
            ETF_ENABLED_CAPABILITIES - set(unavailable),
            dict(unavailable),
        )


def resolve_analysis_capabilities(
    instrument_profile: dict[str, Any] | None,
    analysis_mode: str,
    unavailable: dict[str, str] | None = None,
) -> list[str]:
    """Return deterministic capabilities; unavailable phase 1.5/2 data is omitted."""
    return AnalysisCapabilities.for_instrument(
        instrument_profile, analysis_mode, unavailable
    ).to_list()


def filter_etf_analysts(
    analysts: Sequence[str],
    capabilities: Iterable[str] | None,
) -> tuple[str, ...]:
    """Drop ETF analysts whose required capabilities are not active.

    ``capabilities is None`` means “not yet probed”; keep the full ETF set.
    An explicit empty iterable means every capability-dependent analyst is off.
    """
    if capabilities is None:
        return tuple(analysts)
    enabled = frozenset(capabilities)
    kept: list[str] = []
    for analyst in analysts:
        required = ETF_ANALYST_REQUIRED_CAPABILITIES.get(analyst)
        if required is None or required.issubset(enabled):
            kept.append(analyst)
    return tuple(kept)


def report_field_is_active(field: str, capabilities: Iterable[str] | None) -> bool:
    """True when a report field is allowed by the active capability set."""
    required = ETF_REPORT_FIELD_CAPABILITIES.get(field)
    if required is None:
        return True
    return required.issubset(frozenset(capabilities or ()))
