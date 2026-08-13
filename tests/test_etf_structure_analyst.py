import json

from tradingagents.agents.analysts.etf_structure_analyst import (
    _render_grounded_structure_report,
)


def test_structure_report_preserves_provider_identifier_without_expansion():
    profile = {
        "fund_name": {"value": "机器人ETF易方达"},
        "fund_manager": {"value": "易方达基金"},
        "tracking_index_name": {"value": "国证机器人产业指数"},
        "management_fee": {"value": "0.50%"},
        "custodian_fee": {"value": "0.10%"},
    }
    shares = {
        "shares_and_aum": {
            "value": [
                {"日期": "2026-06-30", "期末总份额（亿份）": 99.96, "期末净资产（亿元）": 159.99}
            ],
            "source": "fixture",
            "as_of": "2026-06-30",
        }
    }
    report = _render_grounded_structure_report(
        ticker="159530",
        trade_date="2026-08-13",
        instrument_profile={
            "reference_instrument": {
                "name": "国证机器人产业指数",
                "code": "980022",
                "provider": "CNI",
                "series_variant": "price",
            }
        },
        profile_text=json.dumps(profile, ensure_ascii=False),
        shares_text=json.dumps(shares, ensure_ascii=False),
    )
    assert "| 指数供应方标识 | CNI |" in report
    assert "中证指数有限公司" not in report
    assert "| 2026-06-30 | 99.96 | 159.99 |" in report
