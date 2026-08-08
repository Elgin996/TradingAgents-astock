import json

from tradingagents.dataflows import etf_data


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
    monkeypatch.setattr(etf_data, "get_etf_quote", lambda symbol: failed)
    monkeypatch.setattr(etf_data, "get_etf_shares_aum", lambda symbol: ok)
    monkeypatch.setattr(etf_data, "get_etf_announcements", lambda symbol, date: ok)

    unavailable = etf_data.probe_etf_capabilities("510300", "2026-08-07")

    assert unavailable == {"liquidity_metrics": "source unavailable"}
