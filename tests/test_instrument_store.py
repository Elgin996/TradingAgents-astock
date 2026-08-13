from tradingagents.dataflows.instrument_store import (
    find_instrument_by_name,
    get_instrument,
    save_completed_instrument,
)


def test_completed_stock_profile_round_trip(tmp_path):
    save_completed_instrument(
        tmp_path,
        "600519",
        "stock",
        {
            "symbol": "600519",
            "exchange": "SSE",
            "security_type": "stock",
            "analysis_product": "a_share_stock",
        },
        {"market_report": "600519 贵州茅台 技术分析"},
        "2026-08-13",
    )

    saved = get_instrument(tmp_path, "600519")
    assert saved is not None
    assert saved["name"] == "贵州茅台"
    assert saved["profile"]["name"] == "贵州茅台"
    assert find_instrument_by_name(tmp_path, "贵州茅台")["symbol"] == "600519"


def test_completed_etf_preserves_fund_name_not_index_name(tmp_path):
    save_completed_instrument(
        tmp_path,
        "510300",
        "etf",
        {
            "symbol": "510300",
            "exchange": "SSE",
            "security_type": "etf",
            "fund_name": "华泰柏瑞沪深300ETF",
            "tracking_index_name": "沪深300指数",
        },
        {},
        "2026-08-13",
    )

    saved = get_instrument(tmp_path, "510300")
    assert saved is not None
    assert saved["name"] == "华泰柏瑞沪深300ETF"
    assert saved["name"] != saved["profile"]["tracking_index_name"]
