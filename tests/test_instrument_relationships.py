from tradingagents.dataflows.analysis_capabilities import resolve_analysis_capabilities_v2
from tradingagents.dataflows.index_master import resolve_index_reference
from tradingagents.dataflows.instrument import profile_for_stock, profile_from_fund_master
from tradingagents.dataflows.security_master import FundMasterRecord, _classify


def test_index_name_matching_is_exact_not_contains():
    assert resolve_index_reference(name="沪深300").status == "verified"
    assert resolve_index_reference(name="中证全指半导体产品与设备指数").status == "missing"


def test_stock_profile_has_product_identity():
    profile = profile_for_stock("600000", exchange="SSE", name="测试股票")
    assert profile.analysis_product == "a_share_stock"
    assert profile.to_dict()["instrument_id"] == "STOCK:SSE:600000"


def test_web_stock_resolution_freezes_v2_profile(monkeypatch):
    from tradingagents.dataflows import security_master
    from web.components.sidebar import _resolve_instrument_profile

    record = FundMasterRecord(
        symbol="600000",
        exchange="SSE",
        fund_name="---",
        fund_type="---",
        tracking_index_name=None,
        fund_manager=None,
        listed_or_established_date=None,
        management_fee=None,
        custodian_fee=None,
        classification="not_a_fund",
        classification_reason="test",
    )
    monkeypatch.setattr(security_master, "resolve_fund_master", lambda code: record)

    mode, profile, error = _resolve_instrument_profile("600000")

    assert error is None
    assert mode == "stock"
    assert profile is not None
    assert profile["analysis_product"] == "a_share_stock"
    assert profile["security_type"] == "stock"


def test_active_etf_is_not_routed_as_tracking_etf():
    fields = {
        "基金全称": "测试主动交易型开放式股票证券投资基金",
        "基金类型": "股票型",
        "跟踪标的": "该基金无跟踪标的",
    }
    classification, _ = _classify(fields)
    assert classification == "active_equity_etf"
    record = FundMasterRecord(
        symbol="561000",
        exchange="SSE",
        fund_name="测试主动ETF",
        fund_type="股票型",
        tracking_index_name=None,
        fund_manager="测试",
        listed_or_established_date="2024-01-01",
        management_fee=None,
        custodian_fee=None,
        classification="active_equity_etf",
        classification_reason="test",
        etf_management_style="active",
    )
    profile = profile_from_fund_master(record)
    assert profile.analysis_product == "active_equity_etf"
    assert profile.reference_instrument is None


def test_v2_capabilities_close_relation_when_reference_is_unavailable():
    profile = profile_for_stock("600000", exchange="SSE").to_dict()
    capabilities = resolve_analysis_capabilities_v2(profile, "a_share_stock")
    assert "subject_price_history" in capabilities.enabled
    assert "formal_tracking_error" not in capabilities.enabled


def test_passive_capabilities_require_a_resolved_reference():
    profile = profile_from_fund_master(
        FundMasterRecord(
            symbol="510300",
            exchange="SSE",
            fund_name="测试 ETF",
            fund_type="指数型-股票",
            tracking_index_name="沪深300",
            fund_manager=None,
            listed_or_established_date=None,
            management_fee=None,
            custodian_fee=None,
            classification="domestic_equity_etf",
            classification_reason="test",
            etf_management_style="passive",
        )
    ).to_dict()
    capabilities = resolve_analysis_capabilities_v2(profile, "passive_equity_etf")
    assert "subject_price_history" in capabilities.enabled
    assert "tracking_index_price_history" not in capabilities.enabled
    assert "series_alignment" not in capabilities.enabled
