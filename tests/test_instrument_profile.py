from tradingagents.dataflows.analysis_capabilities import (
    AnalysisCapabilities,
    resolve_analysis_capabilities,
)
from tradingagents.dataflows.instrument import profile_from_fund_master
from tradingagents.dataflows.security_master import FundMasterRecord


def _record() -> FundMasterRecord:
    return FundMasterRecord(
        symbol="510300",
        exchange="SSE",
        fund_name="沪深300ETF",
        fund_type="指数型-股票",
        tracking_index_name="沪深300",
        fund_manager="测试基金公司",
        listed_or_established_date="2020-01-01",
        management_fee="0.15%",
        custodian_fee="0.05%",
        classification="domestic_equity_etf",
        classification_reason="test",
    )


def test_profile_requires_provider_qualified_tracking_index_code():
    try:
        profile_from_fund_master(_record())
    except ValueError as exc:
        assert "跟踪指数代码" in str(exc)
    else:
        raise AssertionError("missing tracking-index code must block ETF profile")


def test_user_index_code_creates_auditable_etf_profile():
    profile = profile_from_fund_master(
        _record(),
        user_tracking_index_code="000300",
        user_tracking_index_provider="CSI",
    ).to_dict()

    assert profile["security_type"] == "etf"
    assert profile["tracking_index_code"]["value"] == {
        "code": "000300",
        "provider": "CSI",
    }
    assert profile["tracking_index_code"]["notes"] == "user_supplied"
    assert resolve_analysis_capabilities(profile, "etf") == [
        "fund_profile",
        "index_news_policy",
        "liquidity_metrics",
        "price_history",
        "shares_and_aum",
        "technical_indicators",
    ]

    degraded = AnalysisCapabilities.for_instrument(
        profile, "etf", {"shares_and_aum": "Eastmoney disclosure unavailable"}
    )
    assert "shares_and_aum" not in degraded.enabled
    assert degraded.unavailable["shares_and_aum"] == "Eastmoney disclosure unavailable"
