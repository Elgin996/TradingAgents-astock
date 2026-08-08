"""Resolve the capabilities that are valid for a frozen instrument profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
PHASE_CLOSED_CAPABILITIES = {
    "nav_iopv": "阶段 1.5 已关闭：无稳定、可审计的 IOPV 数据源",
    "premium_discount": "阶段 1.5 已关闭：无法保证价格与 IOPV 同时点可比",
    "index_exposure": "阶段 2 已关闭：无许可清晰的指数权重来源",
    "tracking_quality": "阶段 2 已关闭：无稳定指数全收益序列",
    "pcf": "阶段 2 已关闭：无公共、稳定的 PCF 申赎清单来源",
}


@dataclass(frozen=True)
class AnalysisCapabilities:
    """Enabled capabilities plus auditable reasons for omitted capabilities."""

    enabled: frozenset[str]
    unavailable: dict[str, str]

    def to_list(self) -> list[str]:
        return sorted(self.enabled)

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
        if not instrument_profile.get("tracking_index_code"):
            raise ValueError("ETF analysis requires a tracking index code")
        unavailable = {**PHASE_CLOSED_CAPABILITIES, **(unavailable or {})}
        return cls(
            ETF_PHASE_ONE_CAPABILITIES - set(unavailable),
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
