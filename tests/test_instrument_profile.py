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
    assert profile["price_limit_pct"]["value"] == 10
    assert profile["price_limit_pct"]["status"] == "assumed"
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


def test_chinext_theme_derives_20_percent_limit():
    record = FundMasterRecord(
        symbol="159915",
        exchange="SZSE",
        fund_name="易方达创业板ETF",
        fund_type="指数型-股票",
        tracking_index_name="创业板指",
        fund_manager="易方达",
        listed_or_established_date="2011-12-09",
        management_fee="0.50%",
        custodian_fee="0.10%",
        classification="domestic_equity_etf",
        classification_reason="test",
    )
    profile = profile_from_fund_master(
        record,
        user_tracking_index_code="399006",
        user_tracking_index_provider="SZSE",
    ).to_dict()
    assert profile["price_limit_pct"]["value"] == 20
    assert profile["price_limit_pct"]["status"] == "derived"


def test_star_board_etf_code_derives_20_percent_limit():
    record = FundMasterRecord(
        symbol="588000",
        exchange="SSE",
        fund_name="科创50ETF",
        fund_type="指数型-股票",
        tracking_index_name="上证科创板50成份指数",
        fund_manager="华夏",
        listed_or_established_date="2020-11-16",
        management_fee="0.50%",
        custodian_fee="0.10%",
        classification="domestic_equity_etf",
        classification_reason="test",
    )
    profile = profile_from_fund_master(
        record,
        user_tracking_index_code="000688",
        user_tracking_index_provider="SSE",
    ).to_dict()
    assert profile["price_limit_pct"]["value"] == 20
    assert profile["price_limit_pct"]["status"] == "derived"
