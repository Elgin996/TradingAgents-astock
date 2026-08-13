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

# The v2 product model uses series-specific names, while the ETF analyst tools
# still declare the phase-1 capability names.  Keep the translation in one
# place so graph pruning, runtime guards, quality checks, and probe failures all
# make the same decision.
ETF_CAPABILITY_COMPATIBILITY_V2: dict[str, str] = {
    "price_history": "subject_price_history",
    "technical_indicators": "subject_price_indicators",
    "liquidity_metrics": "etf_liquidity_metrics",
    "fund_profile": "fund_profile",
    "shares_and_aum": "etf_shares_and_aum",
    "index_news_policy": "etf_index_news_policy",
    "peer_comparison": "etf_peer_comparison",
}
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

# Product-aware v2 capabilities.  The legacy names above remain unchanged so
# old graph checkpoints and UI code continue to render correctly.
PRODUCT_CAPABILITIES_V2: dict[str, frozenset[str]] = {
    "a_share_stock": frozenset(
        {
            "subject_price_history",
            "subject_price_indicators",
            "subject_volume_indicators",
            "subject_amount_indicators",
            "relative_price_strength",
        }
    ),
    "passive_equity_etf": frozenset(
        {
            "subject_price_history",
            "subject_price_indicators",
            "subject_volume_indicators",
            "subject_amount_indicators",
            "etf_liquidity_metrics",
            "fund_profile",
            "etf_shares_and_aum",
            "etf_index_news_policy",
            "etf_peer_comparison",
            "tracking_index_identity",
            "tracking_index_price_history",
            "tracking_index_price_indicators",
            "series_alignment",
            "relative_price_strength",
            "market_price_path_consistency",
        }
    ),
    "active_equity_etf": frozenset(
        {
            "subject_price_history",
            "subject_price_indicators",
            "subject_volume_indicators",
            "subject_amount_indicators",
            "etf_liquidity_metrics",
            "fund_profile",
            "etf_shares_and_aum",
            "etf_index_news_policy",
            "etf_peer_comparison",
            "benchmark_price_history",
            "benchmark_relative_strength",
        }
    ),
}

CAPABILITY_DEPENDENCIES_V2: dict[str, frozenset[str]] = {
    "series_alignment": frozenset({"subject_price_history", "reference_price_history"}),
    "relative_price_strength": frozenset({"series_alignment"}),
    "market_price_path_consistency": frozenset(
        {"tracking_index_identity", "series_alignment"}
    ),
    "formal_tracking_error": frozenset(
        {"nav_iopv", "total_return_index", "series_alignment"}
    ),
}

V2_CLOSED_CAPABILITIES = {
    "nav_iopv": "第一版关闭：当前没有可审计的 IOPV 序列",
    "premium_discount": "第一版关闭：没有 NAV/IOPV 与 ETF 市场价的同点契约",
    "formal_tracking_error": "第一版关闭：没有 NAV 与全收益指数的匹配序列",
    "formal_tracking_difference": "第一版关闭：没有 NAV 与全收益指数的匹配序列",
    "index_constituent_exposure": "第一版关闭：没有许可清晰的成分权重来源",
    "pcf": "第一版关闭：没有公共、稳定的 PCF 来源",
    "realtime_holdings": "第一版关闭：不推断实时持仓",
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
        analysis_product: str | None = None,
    ) -> "AnalysisCapabilities":
        # Explicit product selection opts into v2.  Omitting it is the legacy
        # compatibility path used by existing graph/UI callers.
        if analysis_product is not None:
            return cls.for_product(
                instrument_profile,
                analysis_product,
                unavailable=unavailable,
            )
        if analysis_mode != "etf":
            return cls(frozenset(), {})
        if not instrument_profile or instrument_profile.get("security_type") != "etf":
            raise ValueError("ETF analysis requires a frozen ETF instrument profile")
        unavailable = {**PHASE_CLOSED_CAPABILITIES, **(unavailable or {})}
        return cls(
            ETF_ENABLED_CAPABILITIES - set(unavailable),
            dict(unavailable),
        )

    @classmethod
    def for_product(
        cls,
        instrument_profile: dict[str, Any] | None,
        analysis_product: str,
        *,
        unavailable: dict[str, str] | None = None,
    ) -> "AnalysisCapabilities":
        if analysis_product not in PRODUCT_CAPABILITIES_V2:
            raise ValueError(f"unsupported analysis_product: {analysis_product}")
        if not instrument_profile:
            raise ValueError("product analysis requires a frozen instrument profile")
        expected_security = "stock" if analysis_product == "a_share_stock" else "etf"
        if instrument_profile.get("security_type") != expected_security:
            raise ValueError(
                f"{analysis_product} requires security_type={expected_security}"
            )
        # Runtime probes currently report the phase-1 names.  Translate them
        # before subtracting from the v2 set; otherwise a failed quote probe
        # removes ``liquidity_metrics`` while incorrectly leaving
        # ``etf_liquidity_metrics`` enabled.
        translated_unavailable = {
            ETF_CAPABILITY_COMPATIBILITY_V2.get(name, name): reason
            for name, reason in (unavailable or {}).items()
        }
        unavailable_map = {**V2_CLOSED_CAPABILITIES, **translated_unavailable}
        reference_payload = instrument_profile.get("reference_instrument")
        reference_ready = False
        if isinstance(reference_payload, dict):
            reference_ready = (
                reference_payload.get("status") in {"verified", "user_supplied"}
                and bool(str(reference_payload.get("code") or "").strip())
                and bool(str(reference_payload.get("provider") or "").strip())
                and reference_payload.get("series_variant") in {
                    "price",
                    "total_return",
                    "net_total_return",
                }
            )
        else:
            # Accept the flattened phase-1 checkpoint shape while old
            # histories migrate to the explicit ReferenceInstrument field.
            tracking_code = instrument_profile.get("tracking_index_code")
            if isinstance(tracking_code, dict):
                tracking_code = tracking_code.get("value")
            if isinstance(tracking_code, dict):
                reference_ready = bool(
                    str(tracking_code.get("code") or "").strip()
                    and str(tracking_code.get("provider") or "").strip()
                    and instrument_profile.get("series_variant") in {
                        "price",
                        "total_return",
                        "net_total_return",
                    }
                )
        if analysis_product == "passive_equity_etf" and not reference_ready:
            unavailable_map.setdefault(
                "tracking_index_identity",
                "未冻结 verified provider/code/variant 的跟踪指数关系；仅运行 ETF 自身分析。",
            )
            unavailable_map.setdefault(
                "tracking_index_price_history",
                "跟踪指数身份或序列口径未确认，关系层不可用。",
            )
        elif analysis_product == "active_equity_etf" and not reference_ready:
            unavailable_map.setdefault(
                "benchmark_price_history",
                "比较基准未确认；主动 ETF 仍可独立分析。",
            )
            unavailable_map.setdefault(
                "benchmark_relative_strength",
                "比较基准未确认；仅保留主动 ETF 自身技术信号。",
            )
        enabled = set(PRODUCT_CAPABILITIES_V2[analysis_product]) - set(unavailable_map)
        # Capabilities whose prerequisites were removed must not remain enabled
        # as a stale label in a report or prompt.
        changed = True
        while changed:
            changed = False
            for capability, prerequisites in CAPABILITY_DEPENDENCIES_V2.items():
                def prerequisite_available(prerequisite: str) -> bool:
                    if prerequisite == "reference_price_history":
                        return bool(
                            {"tracking_index_price_history", "benchmark_price_history"}
                            & enabled
                        )
                    return prerequisite in enabled

                if capability in enabled and not all(
                    prerequisite_available(item) for item in prerequisites
                ):
                    enabled.remove(capability)
                    unavailable_map.setdefault(
                        capability, f"依赖能力缺失：{', '.join(sorted(prerequisites))}"
                    )
                    changed = True
        return cls(frozenset(enabled), unavailable_map)


def resolve_analysis_capabilities(
    instrument_profile: dict[str, Any] | None,
    analysis_mode: str,
    unavailable: dict[str, str] | None = None,
    analysis_product: str | None = None,
) -> list[str]:
    """Return deterministic capabilities; unavailable phase 1.5/2 data is omitted."""
    return AnalysisCapabilities.for_instrument(
        instrument_profile, analysis_mode, unavailable, analysis_product
    ).to_list()


def resolve_analysis_capabilities_v2(
    instrument_profile: dict[str, Any] | None,
    analysis_product: str,
    unavailable: dict[str, str] | None = None,
) -> AnalysisCapabilities:
    """Resolve the product-aware v2 capability set and reasons."""

    return AnalysisCapabilities.for_product(
        instrument_profile, analysis_product, unavailable=unavailable
    )


def capability_dependencies(capability: str) -> frozenset[str]:
    return CAPABILITY_DEPENDENCIES_V2.get(capability, frozenset())


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
        if required is None or required.issubset(enabled) or all(
            ETF_CAPABILITY_COMPATIBILITY_V2.get(item, item) in enabled
            for item in required
        ):
            kept.append(analyst)
    return tuple(kept)


def report_field_is_active(field: str, capabilities: Iterable[str] | None) -> bool:
    """True when a report field is allowed by the active capability set."""
    required = ETF_REPORT_FIELD_CAPABILITIES.get(field)
    if required is None:
        return True
    enabled = frozenset(capabilities or ())
    return required.issubset(enabled) or all(
        ETF_CAPABILITY_COMPATIBILITY_V2.get(item, item) in enabled
        for item in required
    )
