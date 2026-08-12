"""Deterministic shadow-mode comparison for technical-analysis v1/v2."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.dataflows.models import MarketDataResult


class ShadowComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_product: str
    legacy_stance: str
    v2_state: str
    stance_flipped: bool
    legacy_snapshot_id: str = ""
    bundle_snapshot_id: str = ""
    quality_grade: str = "F"
    flags: list[str] = Field(default_factory=list)


def shadow_mode_enabled(config: dict[str, Any], analysis_product: str) -> bool:
    if not bool(config.get("technical_v2_shadow_mode", False)):
        return False
    products = config.get("technical_v2_enabled_products") or []
    return not products or analysis_product in products


def compare_legacy_and_product(
    *,
    analysis_product: str,
    legacy_stance: str,
    product_state: str,
    legacy_snapshot_id: str = "",
    bundle_snapshot_id: str = "",
    quality_grade: str = "F",
    flags: list[str] | None = None,
) -> ShadowComparison:
    confirmed_direction = {
        "bullish_confirmed": "bullish",
        "bearish_confirmed": "bearish",
        "standalone_vehicle_only": legacy_stance,
        "standalone_vehicle": legacy_stance,
    }.get(product_state, "mixed" if product_state == "conflicted" else product_state)
    return ShadowComparison(
        analysis_product=analysis_product,
        legacy_stance=legacy_stance,
        v2_state=product_state,
        stance_flipped=bool(
            legacy_stance in {"bullish", "bearish"}
            and confirmed_direction in {"bullish", "bearish"}
            and legacy_stance != confirmed_direction
        ),
        legacy_snapshot_id=legacy_snapshot_id,
        bundle_snapshot_id=bundle_snapshot_id,
        quality_grade=quality_grade,
        flags=flags or [],
    )


def build_shadow_comparison(
    subject: MarketDataResult,
    *,
    analysis_product: str,
    product_state: str,
    bundle_snapshot_id: str = "",
) -> ShadowComparison:
    """Run the legacy deterministic signal engine on the v2 subject snapshot.

    Shadow mode deliberately reuses the already-fetched subject bars. It adds
    no second network source and cannot change the v2 evidence or final path.
    """

    legacy_stance = "unavailable"
    flags: list[str] = []
    if subject.quality.decision == "block" or not subject.bars:
        flags.append("legacy_subject_unavailable")
    else:
        try:
            from tradingagents.technical.indicators import IndicatorEngine
            from tradingagents.technical.signals import SignalEngine

            engine = IndicatorEngine()
            frame = engine.calculate_frame(subject.bars)
            evaluation = SignalEngine(engine.config).run(
                frame,
                quality_grade=subject.quality.grade,
                snapshot_id=subject.snapshot_id or "",
            )
            legacy_stance = evaluation.assessment.stance
        except Exception as exc:  # pragma: no cover - defensive shadow path
            flags.append(f"legacy_engine_error:{type(exc).__name__}")
    return compare_legacy_and_product(
        analysis_product=analysis_product,
        legacy_stance=legacy_stance,
        product_state=product_state,
        legacy_snapshot_id=subject.snapshot_id or "",
        bundle_snapshot_id=bundle_snapshot_id,
        quality_grade=subject.quality.grade,
        flags=flags,
    )
