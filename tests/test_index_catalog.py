from tradingagents.dataflows.index_catalog import (
    infer_tracking_index_provider,
    lookup_tracking_index_code,
    normalize_tracking_index_name,
)
from tradingagents.dataflows.instrument import profile_from_fund_master
from tradingagents.dataflows.security_master import FundMasterRecord


def test_normalize_strips_price_and_index_suffixes():
    assert normalize_tracking_index_name("创业板指数(价格)") == "创业板"
    assert normalize_tracking_index_name("沪深300指数") == "沪深300"
    assert normalize_tracking_index_name("上证科创板50成份指数") == "上证科创板50成份"


def test_catalog_maps_common_indices():
    assert lookup_tracking_index_code("沪深300指数") == ("000300", "CSI")
    assert lookup_tracking_index_code("创业板指数(价格)") == ("399006", "SZSE")
    assert lookup_tracking_index_code("上证科创板50成份指数") == ("000688", "SSE")
    assert lookup_tracking_index_code("中证全指半导体产品与设备指数") is None


def test_provider_is_inferred_without_user_input():
    assert infer_tracking_index_provider("000300") == "CSI"
    assert infer_tracking_index_provider("931865", "中证全指半导体指数") == "CSI"
    assert infer_tracking_index_provider("987654", "未收录主题指数") == "UNKNOWN"


def test_catalog_profile_is_auditable_and_not_user_supplied():
    record = FundMasterRecord(
        symbol="510300",
        exchange="SSE",
        fund_name="沪深300ETF",
        fund_type="指数型-股票",
        tracking_index_name="沪深300指数",
        fund_manager="测试",
        listed_or_established_date="2012-05-04",
        management_fee="0.15%",
        custodian_fee="0.05%",
        classification="domestic_equity_etf",
        classification_reason="test",
        tracking_index_code="000300",
        tracking_index_provider="CSI",
        tracking_index_code_source="catalog",
    )
    profile = profile_from_fund_master(record).to_dict()
    assert profile["tracking_index_code"]["source"] == "index_catalog"
    assert profile["tracking_index_code"]["notes"] == "catalog"
    assert profile["tracking_index_code"]["value"] == {
        "code": "000300",
        "provider": "CSI",
    }
