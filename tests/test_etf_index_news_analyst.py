import json

from tradingagents.agents.analysts.etf_index_news_analyst import (
    _news_payload_status,
    _render_grounded_index_news_report,
)


def test_index_news_report_only_renders_supplied_evidence():
    announcements = {
        "announcements": {
            "value": [
                {"PUBLISHDATE": "2026-08-11T00:00:00", "TITLE": "产品资料概要更新"}
            ],
            "status": "ok",
        }
    }
    report = _render_grounded_index_news_report(
        ticker="159530",
        index_code="980022",
        trade_date="2026-08-13",
        start_date="2026-08-01",
        index_news="### 国证机器人产业指数新闻 (source: fixture)",
        global_news="No news found in fixture",
        announcements_text=json.dumps(announcements, ensure_ascii=False),
    )
    assert "980022" in report
    assert "产品资料概要更新" in report
    assert "159901" not in report
    assert "不生成工具未返回的事件" in report


def test_news_payload_status_does_not_mark_vendor_failure_as_available():
    assert _news_payload_status("[数据缺失: 跟踪指数新闻] source offline") == "不可得"
    assert _news_payload_status("No news found in fixture") == "无命中"
    assert _news_payload_status("### 有日期与来源的新闻") == "可用"
