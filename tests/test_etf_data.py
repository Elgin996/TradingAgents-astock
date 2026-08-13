import json
from datetime import datetime, timezone

from tradingagents.dataflows import etf_data

_TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
_PAST = "2020-01-01"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_announcements_accepts_eastmoney_data_list_and_filters_future_items(monkeypatch):
    monkeypatch.setattr(
        etf_data,
        "_em_get",
        lambda *args, **kwargs: _Response(
            {
                "Data": [
                    {"TITLE": "已发布", "PUBLISHDATE": "2026-08-07T00:00:00"},
                    {"TITLE": "未来公告", "PUBLISHDATE": "2026-08-08T00:00:00"},
                    {"TITLE": "无日期公告"},
                ]
            }
        ),
    )

    payload = json.loads(etf_data.get_etf_announcements("510300", "2026-08-07"))

    assert payload["announcements"]["status"] == "ok"
    assert [item["TITLE"] for item in payload["announcements"]["value"]] == ["已发布"]


def test_capability_probe_removes_only_failed_sources(monkeypatch):
    ok = '{"data": {"status": "ok"}}'
    failed = '{"data": {"status": "error", "notes": "source unavailable"}}'
    monkeypatch.setattr(etf_data, "get_etf_profile", lambda symbol: ok)
    monkeypatch.setattr(etf_data, "get_etf_quote", lambda symbol, end_date=None: failed)
    monkeypatch.setattr(etf_data, "get_etf_shares_aum", lambda symbol: ok)
    monkeypatch.setattr(etf_data, "get_etf_announcements", lambda symbol, date: ok)

    unavailable = etf_data.probe_etf_capabilities("510300", _TODAY)

    assert unavailable == {"liquidity_metrics": "source unavailable"}


def test_capability_probe_removes_liquidity_metrics_for_past_trade_date(monkeypatch):
    ok = '{"data": {"status": "ok"}}'
    monkeypatch.setattr(etf_data, "get_etf_profile", lambda symbol: ok)
    monkeypatch.setattr(etf_data, "get_etf_shares_aum", lambda symbol: ok)
    monkeypatch.setattr(etf_data, "get_etf_announcements", lambda symbol, date: ok)

    unavailable = etf_data.probe_etf_capabilities("510300", _PAST)

    assert "liquidity_metrics" in unavailable


class _FundRecord:
    def __init__(self, **kwargs):
        self.symbol = kwargs["symbol"]
        self.fund_name = kwargs.get("fund_name", self.symbol)
        self.tracking_index_name = kwargs.get("tracking_index_name", "沪深300指数")
        self.fund_manager = kwargs.get("fund_manager", "测试基金")
        self.management_fee = kwargs.get("management_fee", "0.50%")
        self.custodian_fee = kwargs.get("custodian_fee", "0.10%")
        self.classification = kwargs.get("classification", "domestic_equity_etf")


def test_peer_comparison_resolves_subject_profile_exactly_once(monkeypatch):
    """§5.3: get_etf_peer_comparison must not re-resolve the subject's profile."""
    calls: list[str] = []

    def _resolve(symbol, **_kwargs):
        calls.append(symbol)
        return _FundRecord(symbol=symbol, fund_name=f"ETF{symbol}")

    monkeypatch.setattr(etf_data, "resolve_fund_master", _resolve)
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

    assert payload["peer_comparison"]["status"] == "ok"
    assert calls.count("510300") == 1
    assert calls.count("159919") == 1
