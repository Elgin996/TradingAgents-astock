import json

from langchain_core.messages import ToolMessage

from tradingagents.agents.analysts.etf_compare_analyst import (
    _render_grounded_comparison_report,
)


def test_comparison_report_cannot_add_unreturned_peers_or_alerts():
    peer = {
        "peer_comparison": {
            "value": {
                "tracking_index_name": "国证机器人产业指数",
                "peers": [
                    {
                        "symbol": "159530",
                        "fund_name": "机器人ETF易方达",
                        "management_fee": "0.50%",
                        "custodian_fee": "0.10%",
                        "shares_yi": 99.96,
                        "aum_yi": 159.99,
                        "turnover_pct": 3.04,
                        "float_mcap_yi": 186.75,
                        "shares_as_of": "2026-06-30",
                        "status": "ok",
                    }
                ],
                "excluded_fields": ["premium_discount", "tracking_quality"],
            },
            "source": "audited peer tool",
            "as_of": "2026-08-13",
            "status": "missing",
        }
    }
    alerts = {
        "structure_alerts": {
            "value": {"alerts": [], "excluded_rules": ["tracking_error_spike"]},
            "source": "audited alerts tool",
            "as_of": "2026-08-13",
            "status": "ok",
        }
    }
    report = _render_grounded_comparison_report(
        [
            ToolMessage(json.dumps(peer, ensure_ascii=False), name="get_etf_peer_comparison", tool_call_id="1"),
            ToolMessage(json.dumps(alerts, ensure_ascii=False), name="get_etf_structure_alerts", tool_call_id="2"),
        ],
        "159530",
        "2026-08-13",
    )
    assert report is not None
    assert "159530" in report
    assert "159901" not in report
    assert "仅取得主体自身，不能形成同类排名" in report
    assert "工具未返回触发的结构预警" in report
