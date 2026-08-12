"""Evidence bundle consumed by report renderers and fact validators."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from tradingagents.dataflows.models import MarketDataResult, TechnicalAssessment, TechnicalSignal


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    kind: str
    value: Any
    observed_at: date | None = None
    source: str | None = None


class TechnicalEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    symbol: str
    analysis_start: date
    analysis_end: date
    calculation_start: date | None = None
    snapshot_id: str | None = None
    data_quality_grade: str
    data_quality_decision: str
    source_status: str
    source_attempts: list[dict[str, Any]] = Field(default_factory=list)
    latest_bar: dict[str, Any] = Field(default_factory=dict)
    interval_statistics: dict[str, Any] = Field(default_factory=dict)
    indicators: dict[str, Any] = Field(default_factory=dict)
    signals: list[TechnicalSignal] = Field(default_factory=list)
    assessment: TechnicalAssessment | None = None
    levels: dict[str, Any] = Field(default_factory=dict)
    missing_items: list[str] = Field(default_factory=list)
    prohibited_items: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    data_contract_version: str = "market-data-v1"
    indicator_config_version: str = "indicator-config-v1"
    signal_rule_version: str = "technical-signal-v1"

    def allowed_values(self) -> set[str]:
        values: set[str] = set()
        for item in self.evidence:
            values.add(str(item.value))
        return values

    def to_prompt(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2, default=str)


def _safe_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, 10)
    return value


def _bundle_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()
    return "evidence:" + hashlib.sha256(raw).hexdigest()


def build_evidence_bundle(
    result: MarketDataResult,
    *,
    indicator_frame: pd.DataFrame | None = None,
    signals: list[TechnicalSignal] | None = None,
    assessment: TechnicalAssessment | None = None,
    interval_statistics: dict[str, Any] | None = None,
    prohibited_items: list[str] | None = None,
    display_start: date | None = None,
) -> TechnicalEvidenceBundle:
    latest = result.bars[-1] if result.bars else None
    latest_bar = latest.model_dump(mode="json") if latest else {}
    indicators: dict[str, Any] = {}
    levels: dict[str, Any] = {}
    if indicator_frame is not None and not indicator_frame.empty:
        row = indicator_frame.iloc[-1]
        for name, value in row.items():
            if name in {"trade_date", "open", "high", "low", "close", "volume", "amount"}:
                continue
            safe = _safe_value(value)
            indicators[name] = safe
            if name.startswith("rolling_") or name.startswith("close_sma_"):
                levels[name] = safe
    evidence: list[EvidenceItem] = []
    for kind, values in (("price", latest_bar), ("indicator", indicators), ("level", levels)):
        for name, value in values.items():
            if value is not None:
                evidence.append(
                    EvidenceItem(
                        evidence_id=f"{kind}.{name}",
                        kind=kind,
                        value=value,
                        observed_at=latest.trade_date if latest else None,
                        source=latest.source if latest else None,
                    )
                )
    for signal in signals or []:
        evidence.append(
            EvidenceItem(
                evidence_id=f"signal.{signal.signal_id}",
                kind="signal",
                value=signal.direction,
                observed_at=signal.observed_at,
            )
        )
        evidence.append(
            EvidenceItem(
                evidence_id=f"signal.{signal.signal_id}.strength",
                kind="signal_strength",
                value=round(signal.strength, 10),
                observed_at=signal.observed_at,
            )
        )
        evidence.append(
            EvidenceItem(
                evidence_id=f"signal.{signal.signal_id}.confidence",
                kind="signal_confidence",
                value=round(signal.confidence, 10),
                observed_at=signal.observed_at,
            )
        )
    payload = {
        "symbol": result.request.symbol,
        "request": result.request.model_dump(mode="json"),
        "snapshot_id": result.snapshot_id,
        "quality": result.quality.model_dump(mode="json"),
        "latest_bar": latest_bar,
        "indicators": indicators,
        "signals": [signal.model_dump(mode="json") for signal in signals or []],
    }
    bundle_id = _bundle_id(payload)
    return TechnicalEvidenceBundle(
        bundle_id=bundle_id,
        symbol=result.request.symbol,
        analysis_start=display_start or result.request.start_date,
        analysis_end=result.request.end_date,
        calculation_start=result.request.start_date,
        snapshot_id=result.snapshot_id,
        data_quality_grade=result.quality.grade,
        data_quality_decision=result.quality.decision,
        source_status=result.quality.source_status,
        source_attempts=[attempt.model_dump(mode="json") for attempt in result.attempts],
        latest_bar=latest_bar,
        interval_statistics=interval_statistics or {},
        indicators=indicators,
        signals=signals or [],
        assessment=assessment,
        levels=levels,
        missing_items=list(result.quality.flags) + (["bars"] if not result.bars else []),
        prohibited_items=prohibited_items or [],
        evidence=evidence,
    )


def render_evidence_bundle(bundle: TechnicalEvidenceBundle) -> str:
    """Render a bounded report from verified facts, without inventing values."""
    lines = [
        f"数据质量：{bundle.data_quality_grade} / {bundle.source_status}",
        f"实际来源尝试：{', '.join(item.get('source', '') + ':' + item.get('status', '') for item in bundle.source_attempts)}",
        f"数据区间：{bundle.analysis_start.isoformat()} → {bundle.analysis_end.isoformat()}",
        f"快照：{bundle.snapshot_id or 'unavailable'}",
        f"信号规则：{bundle.signal_rule_version}",
        "",
        "## 已验证行情与指标",
    ]
    if bundle.latest_bar:
        lines.append("| 日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        bar = bundle.latest_bar
        lines.append(
            f"| {bar.get('trade_date', '—')} | {bar.get('open', '—')} | {bar.get('high', '—')} | {bar.get('low', '—')} | {bar.get('close', '—')} | {bar.get('volume', '—')} |"
        )
    for name, value in bundle.indicators.items():
        if value is not None:
            lines.append(f"- `{name}` = {value}")
    lines.extend(["", "## 确定性信号", "| 信号 | 类别 | 方向 | 强度 | 置信度 |", "|---|---|---|---:|---:|"])
    for signal in bundle.signals:
        lines.append(f"| {signal.signal_id} | {signal.category} | {signal.direction} | {signal.strength:.4f} | {signal.confidence:.4f} |")
    if bundle.assessment:
        lines.extend([
            "",
            f"综合技术判断：{bundle.assessment.stance}",
            f"规则汇总分数：{bundle.assessment.score:.4f}",
            f"判断置信度：{bundle.assessment.confidence:.4f}",
            f"数据决策：{bundle.assessment.decision}",
        ])
    if bundle.missing_items:
        lines.extend(["", "数据缺失/限制：", *[f"- {item}" for item in bundle.missing_items]])
    if bundle.data_quality_decision == "block":
        lines.extend(["", "⚠️ 数据门控为 block：只能说明不可判断，不输出方向性结论。"])
    elif bundle.data_quality_decision == "observe_only":
        lines.extend(["", "⚠️ 数据门控为 observe_only：以上内容仅作观察性证据，不构成执行性结论。"])
    return "\n".join(lines)
