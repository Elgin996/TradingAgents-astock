"""§4 regression: stock-mode prompts must retain the full A-Share frameworks.

Phrase assertions rather than full-text comparison so normal prose edits do
not brittle-break this test; each phrase anchors a specific fact that the
2026-08 ETF refactor deleted from the stock-mode debate/risk prompts.
"""

from __future__ import annotations

from tradingagents.agents.utils.agent_utils import (
    build_debate_framework,
    build_risk_framework,
    build_trading_constraints,
)


def test_bull_debate_framework_stock_mode_has_ashare_phrases():
    text = build_debate_framework("stock", "bull")
    for phrase in (
        "Northbound Capital",
        "北向资金",
        "Hot Money Momentum",
        "PE digestion timeframe",
        "Lockup Expiry Cleared",
    ):
        assert phrase in text


def test_bear_debate_framework_stock_mode_has_ashare_phrases():
    text = build_debate_framework("stock", "bear")
    for phrase in (
        "Policy Headwinds",
        "窗口指导",
        "Hot Money Withdrawal",
        "T+1 Trap",
        "Northbound Retreat",
    ):
        assert phrase in text


def test_debate_framework_etf_mode_excludes_ashare_phrases():
    for side in ("bull", "bear"):
        text = build_debate_framework("etf", side)
        for phrase in ("Northbound Capital", "窗口指导", "涨停板效应", "Lockup Expiry Overhang"):
            assert phrase not in text


def test_aggressive_risk_framework_stock_mode_has_ashare_phrases():
    text = build_risk_framework("stock", "aggressive")
    for phrase in (
        "涨停板效应",
        "Policy-Driven Sectors",
        "Northbound Validation",
        "PE Expansion Phase",
    ):
        assert phrase in text


def test_conservative_risk_framework_stock_mode_has_ashare_phrases():
    text = build_risk_framework("stock", "conservative")
    for phrase in (
        "涨跌停板",
        "Lockup Expiry Overhang",
        "ST/Delisting Risk",
        "T+1 Settlement Lock",
    ):
        assert phrase in text


def test_neutral_risk_framework_stock_mode_has_ashare_phrases():
    text = build_risk_framework("stock", "neutral")
    for phrase in (
        "Northbound Flow as Smart Money Gauge",
        "Sector Rotation Awareness",
        "Position Sizing over Direction",
    ):
        assert phrase in text


def test_risk_framework_etf_mode_excludes_ashare_phrases():
    for posture in ("aggressive", "conservative", "neutral"):
        text = build_risk_framework("etf", posture)
        for phrase in ("涨停板效应", "Lockup Expiry Overhang", "ST/Delisting Risk", "北向资金"):
            assert phrase not in text


def test_trading_constraints_stock_mode_has_st_and_margin_lines():
    text = build_trading_constraints("stock")
    assert "ST/delisting" in text
    assert "Margin eligibility" in text


def test_trading_constraints_etf_mode_unchanged():
    text = build_trading_constraints("etf")
    assert "ST/delisting" not in text
    assert "Margin eligibility" not in text
    assert "ETF trading constraints" in text
