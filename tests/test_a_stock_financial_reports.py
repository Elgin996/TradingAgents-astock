from tradingagents.dataflows import a_stock


def test_sina_report_list_format_is_normalized(monkeypatch):
    class Response:
        def json(self):
            return {
                "result": {
                    "data": {
                        "report_list": {
                            "20260331": {
                                "data": [
                                    {"item_field": "CURFDS", "item_title": "货币资金", "item_value": "123"},
                                    {"item_field": "ASSET", "item_title": "资产总计", "item_value": "456"},
                                ]
                            },
                            "20260630": {
                                "data": [
                                    {"item_field": "CURFDS", "item_title": "货币资金", "item_value": "789"},
                                ]
                            },
                        }
                    }
                }
            }

    monkeypatch.setattr(a_stock._requests, "get", lambda *args, **kwargs: Response())

    result = a_stock._get_financial_report_sina(
        "300750", "资产负债表", "quarterly", "2026-03-31"
    )

    assert list(result["报告日"].dt.strftime("%Y-%m-%d")) == ["2026-03-31"]
    assert result.iloc[0]["货币资金"] == "123"
    assert result.iloc[0]["资产总计"] == "456"


def test_sina_report_list_format_supports_annual_filter(monkeypatch):
    class Response:
        def json(self):
            return {
                "result": {
                    "data": {
                        "report_list": {
                            "20260331": {"data": [{"item_title": "资产总计", "item_value": "1"}]},
                            "20251231": {"data": [{"item_title": "资产总计", "item_value": "2"}]},
                        }
                    }
                }
            }

    monkeypatch.setattr(a_stock._requests, "get", lambda *args, **kwargs: Response())

    result = a_stock._get_financial_report_sina(
        "300750", "资产负债表", "annual", "2026-12-31"
    )

    assert len(result) == 1
    assert result.iloc[0]["资产总计"] == "2"
