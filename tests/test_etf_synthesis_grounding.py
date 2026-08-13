from tradingagents.agents.utils.etf_synthesis_grounding import (
    grounded_portfolio_decision,
    has_unsupported_etf_synthesis,
)


def _state():
    return {
        "analysis_mode": "etf",
        "market_data_decision": "allow",
        "market_data_quality": {"grade": "B"},
        "technical_assessment": {
            "product_state": "conflicted",
            "subject_stance": "mixed",
            "reference_stance": "mixed",
            "alignment_state": "weak_divergence",
        },
    }


def test_unsupported_closed_or_peer_claims_trigger_grounding():
    state = _state()
    assert has_unsupported_etf_synthesis("溢价率持续高于1.5%则卖出", state)
    assert has_unsupported_etf_synthesis("相对同类机器人ETF明显转弱", state)
    assert has_unsupported_etf_synthesis("指数受到10%涨跌幅限制", state)
    assert not has_unsupported_etf_synthesis("折溢价数据不可得，仅作为限制。", state)


def test_grounded_decision_preserves_rating_without_invented_thresholds():
    decision = grounded_portfolio_decision(_state(), "Hold")
    assert "**Rating**: Hold" in decision
    assert "产品状态 conflicted" in decision
    assert "1.5%" not in decision
    assert "相对同类" not in decision
