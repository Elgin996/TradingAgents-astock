import json
from datetime import datetime, timezone

from tradingagents.dataflows import etf_data

_TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
from tradingagents.dataflows.analysis_capabilities import AnalysisCapabilities
from tradingagents.dataflows.capability_guard import (
    CapabilityError,
    assert_tool_allowed,
    reset_active_capabilities,
    set_active_capabilities,
)
from tradingagents.graph.checkpointer import thread_id


class _FundRecord:
    def __init__(self, **kwargs):
        self.symbol = kwargs["symbol"]
        self.fund_name = kwargs.get("fund_name", self.symbol)
        self.tracking_index_name = kwargs.get("tracking_index_name", "沪深300指数")
        self.fund_manager = kwargs.get("fund_manager", "测试基金")
        self.management_fee = kwargs.get("management_fee", "0.50%")
        self.custodian_fee = kwargs.get("custodian_fee", "0.10%")
        self.classification = kwargs.get("classification", "domestic_equity_etf")


def test_discover_peer_codes_filters_non_listed_and_keeps_subject(monkeypatch):
    monkeypatch.setattr(
        etf_data,
        "_fund_search",
        lambda key: (
            {"CODE": "159919", "NAME": "沪深300ETF嘉实", "FundBaseInfo": {"FTYPE": "指数型-股票"}},
            {"CODE": "007300", "NAME": "联接基金", "FundBaseInfo": {"FTYPE": "指数型-股票"}},
            {"CODE": "513310", "NAME": "跨境ETF", "FundBaseInfo": {"FTYPE": "指数型-海外股票"}},
            {"CODE": "510330", "NAME": "沪深300ETF华夏", "FundBaseInfo": {"FTYPE": "指数型-股票"}},
        ),
    )
    codes = etf_data.discover_peer_etf_codes("510300", "沪深300指数", limit=8)
    assert codes[0] == "510300"
    assert "159919" in codes
    assert "510330" in codes
    assert "007300" not in codes
    assert "513310" not in codes


def test_structure_alerts_detect_share_spike_and_skip_closed_rules(monkeypatch):
    monkeypatch.setattr(
        etf_data,
        "get_etf_shares_aum",
        lambda symbol: json.dumps(
            {
                "shares_and_aum": {
                    "status": "stale",
                    "as_of": "2026-06-30",
                    "value": [
                        {
                            "日期": "2026-06-30",
                            "期末总份额（亿份）": "100",
                            "期末净资产（亿元）": "200",
                            "净资产变动率": "-40%",
                        },
                        {
                            "日期": "2026-03-31",
                            "期末总份额（亿份）": "200",
                            "期末净资产（亿元）": "400",
                            "净资产变动率": "10%",
                        },
                    ],
                }
            }
        ),
    )
    monkeypatch.setattr(
        etf_data,
        "_tencent_quote",
        lambda codes: {codes[0]: {"turnover_pct": 0.05, "price": 1.0}},
    )

    payload = json.loads(etf_data.get_etf_structure_alerts("510300", _TODAY))
    alerts = payload["structure_alerts"]["value"]["alerts"]
    rules = {item["rule"] for item in alerts}
    assert "share_change_spike" in rules
    assert "aum_shrink" in rules
    assert "liquidity_thin" in rules
    assert "premium_discount_abnormal" not in rules
    assert "premium_discount_abnormal" in payload["structure_alerts"]["value"]["excluded_rules"]


def test_peer_comparison_excludes_closed_fields(monkeypatch):
    monkeypatch.setattr(
        etf_data,
        "resolve_fund_master",
        lambda symbol, **_kwargs: _FundRecord(
            symbol=symbol, fund_name=f"ETF{symbol}"
        ),
    )
    monkeypatch.setattr(
        etf_data,
        "discover_peer_etf_codes",
        lambda symbol, index_name, limit=8: ["510300", "159919"],
    )
    monkeypatch.setattr(
        etf_data,
        "_tencent_quote",
        lambda codes: {
            code: {"price": 1.2, "turnover_pct": 1.5, "float_mcap_yi": 100.0}
            for code in codes
        },
    )
    monkeypatch.setattr(
        etf_data,
        "_latest_shares_row",
        lambda symbol: (
            {"期末总份额（亿份）": "10", "期末净资产（亿元）": "50"},
            "2026-06-30",
            "stale",
        ),
    )

    payload = json.loads(etf_data.get_etf_peer_comparison("510300", _TODAY, max_peers=4))
    point = payload["peer_comparison"]
    assert point["status"] == "ok"
    assert "premium_discount" in point["value"]["excluded_fields"]
    assert "tracking_quality" in point["value"]["excluded_fields"]
    assert {row["symbol"] for row in point["value"]["peers"]} == {"510300", "159919"}


def test_phase_three_capability_enabled_by_default():
    caps = AnalysisCapabilities.for_instrument(
        {
            "security_type": "etf",
            "tracking_index_code": {"value": {"code": "000300", "provider": "CSI"}},
        },
        "etf",
    )
    assert "peer_comparison" in caps.enabled
    assert "premium_discount" not in caps.enabled


def test_structure_alert_tools_require_peer_comparison_capability():
    token = set_active_capabilities(["fund_profile", "liquidity_metrics"])
    try:
        try:
            assert_tool_allowed("get_etf_peer_comparison")
            raised = False
        except CapabilityError:
            raised = True
        assert raised
    finally:
        reset_active_capabilities(token)


def test_etf_checkpoint_schema_bumped_for_stage3():
    assert thread_id("510300", "2026-08-08", "etf") == thread_id(
        "510300", "2026-08-08", "etf", "etf-v1.3"
    )
    assert thread_id("510300", "2026-08-08", "etf", "etf-v1") != thread_id(
        "510300", "2026-08-08", "etf", "etf-v1.3"
    )
