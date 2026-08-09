"""Unit tests for the phase-0 ETF securities-master adapter."""

import pytest

from tradingagents.dataflows import security_master


@pytest.mark.unit
def test_profile_parser_extracts_the_fund_identity_fields(monkeypatch):
    class Response:
        text = """
        <table>
          <tr><td>基金全称</td><td>华泰柏瑞沪深300交易型开放式指数证券投资基金</td>
              <td>基金简称</td><td>沪深300ETF华泰柏瑞</td></tr>
          <tr><td>基金代码</td><td>510300（主代码）</td>
              <td>基金类型</td><td>指数型-股票</td></tr>
          <tr><td>成立日期/规模</td><td>2012年05月04日 / 329.686亿份</td>
              <td>跟踪标的</td><td>沪深300指数</td></tr>
          <tr><td>基金管理人</td><td>华泰柏瑞基金</td>
              <td>管理费率</td><td>0.15%（每年）</td></tr>
        </table>
        """

        def raise_for_status(self):
            return None

    monkeypatch.setattr(security_master.requests, "get", lambda *args, **kwargs: Response())

    fields = security_master._fetch_profile_fields("510300")

    assert fields["基金类型"] == "指数型-股票"
    assert fields["跟踪标的"] == "沪深300指数"
    assert fields["管理费率"] == "0.15%（每年）"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("fields", "expected_classification"),
    [
        (
            {
                "基金全称": "华泰柏瑞沪深300交易型开放式指数证券投资基金",
                "基金类型": "指数型-股票",
                "跟踪标的": "沪深300指数",
            },
            "domestic_equity_etf",
        ),
        (
            {
                "基金全称": "上证5年期国债交易型开放式指数证券投资基金",
                "基金类型": "指数型-固收",
                "跟踪标的": "上证5年期国债指数",
            },
            "unsupported_etf",
        ),
        (
            {
                "基金全称": "博时标普500交易型开放式指数证券投资基金",
                "基金类型": "指数型-海外股票",
                "跟踪标的": "标准普尔500指数",
            },
            "unsupported_etf",
        ),
        (
            {
                "基金全称": "富国天惠精选成长混合型证券投资基金(LOF)",
                "基金类型": "混合型-偏股",
                "跟踪标的": "该基金无跟踪标的",
            },
            "not_etf",
        ),
    ],
)
def test_classification_rejects_out_of_scope_products(fields, expected_classification):
    classification, _ = security_master._classify(fields)

    assert classification == expected_classification


@pytest.mark.unit
def test_resolve_fund_master_combines_independent_exchange_and_type_sources(monkeypatch):
    fields = {
        "基金全称": "华泰柏瑞沪深300交易型开放式指数证券投资基金",
        "基金简称": "沪深300ETF华泰柏瑞",
        "基金类型": "指数型-股票",
        "跟踪标的": "沪深300指数",
        "基金管理人": "华泰柏瑞基金",
        "成立日期/规模": "2012年05月04日 / 329.686亿份",
        "管理费率": "0.15%（每年）",
        "托管费率": "0.05%（每年）",
    }
    monkeypatch.setattr(security_master, "_lookup_exchange", lambda code: "SSE")
    monkeypatch.setattr(security_master, "_fetch_profile_fields", lambda code: fields)

    record = security_master.resolve_fund_master("510300")

    assert record.symbol == "510300"
    assert record.exchange == "SSE"
    assert record.classification == "domestic_equity_etf"
    assert record.tracking_index_name == "沪深300指数"
    assert record.tracking_index_code == "000300"
    assert record.tracking_index_provider == "CSI"
    assert record.tracking_index_code_source == "catalog"


@pytest.mark.unit
def test_user_supplied_index_code_preserves_master_data_facts(monkeypatch):
    fields = {
        "基金全称": "华泰柏瑞沪深300交易型开放式指数证券投资基金",
        "基金简称": "沪深300ETF华泰柏瑞",
        "基金类型": "指数型-股票",
        "跟踪标的": "沪深300指数",
    }
    monkeypatch.setattr(security_master, "_lookup_exchange", lambda code: "SSE")
    monkeypatch.setattr(security_master, "_fetch_profile_fields", lambda code: fields)
    record = security_master.resolve_fund_master("510300")

    updated = security_master.with_user_supplied_tracking_index_code(
        record, code="000300", provider="CSI"
    )

    assert updated.exchange == "SSE"
    assert updated.classification == "domestic_equity_etf"
    assert updated.tracking_index_name == "沪深300指数"
    assert updated.tracking_index_code == "000300"
    assert updated.tracking_index_provider == "CSI"
    assert updated.tracking_index_code_source == "user_supplied"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("code", "provider"),
    [("../000300", "CSI"), ("000300", "CSI<script>"), ("", "CSI")],
)
def test_user_supplied_index_code_requires_safe_code_and_provider(monkeypatch, code, provider):
    fields = {
        "基金全称": "华泰柏瑞沪深300交易型开放式指数证券投资基金",
        "基金类型": "指数型-股票",
        "跟踪标的": "沪深300指数",
    }
    monkeypatch.setattr(security_master, "_lookup_exchange", lambda symbol: "SSE")
    monkeypatch.setattr(security_master, "_fetch_profile_fields", lambda symbol: fields)
    record = security_master.resolve_fund_master("510300")

    with pytest.raises(ValueError):
        security_master.with_user_supplied_tracking_index_code(
            record, code=code, provider=provider
        )
