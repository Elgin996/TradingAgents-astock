"""未来函数防护（point-in-time）。

在历史日期上跑分析时，数据层不能把"今天"的数据当成"分析日当天"的事实交给模型
——报告里完全看不出来，但结论已经被污染了。上游 TradingAgents 把这类问题统称为
backtesting date fidelity（#475）。

本仓库审出三个函数收了日期参数却完全没用：`get_fund_flow`（今天的分钟资金流 +
从今天回溯 20 日）、`get_fundamentals`（腾讯实时估值）、`get_profit_forecast`
（当前一致预期）。前者能真正做时点截断；后两者的数据源根本不提供历史时点值，
补不上就必须**说出来**，而不是静默把今天的数字当历史事实。
"""

from datetime import datetime, timedelta

import pytest

from tradingagents.dataflows import a_stock


TODAY = datetime.now().strftime("%Y-%m-%d")
PAST = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 判定本身
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (PAST, True),
        (TODAY, False),
        ((datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"), False),
        ("", False),
        (None, False),
        ("not-a-date", False),          # 解析不了不能当成历史，否则误伤实时分析
        (f"{PAST} 09:30:00", True),     # 带时分秒也要认得
    ],
)
def test_is_historical(value, expected):
    assert a_stock._is_historical(value) is expected


def test_snapshot_notice_names_the_date_and_says_do_not_use():
    notice = a_stock._snapshot_notice(PAST, "估值")

    assert PAST in notice
    assert "实时快照" in notice
    assert "不得" in notice   # 必须给模型明确指令，光提示"这是实时的"不够


# ---------------------------------------------------------------------------
# get_fund_flow：真正的时点截断
# ---------------------------------------------------------------------------


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def fake_em(monkeypatch):
    """假的东财返回：历史段跨越分析日前后，用来验证截断。"""
    calls = []

    def fake_get(url, params=None, timeout=10):
        calls.append(url)
        if "push2his" in url:
            return FakeResp({"data": {"klines": [
                "2026-05-01,1000,0,0,0,0,0",
                f"{PAST},2000,0,0,0,0,0",
                "2099-01-01,999999,0,0,0,0,0",   # 分析日之后 → 必须被剔除
            ]}})
        return FakeResp({"data": {"klines": [
            "2099-01-01 09:31,111,0,0,0,0,0",     # 实时段 → 复盘时整段不该取
        ]}})

    monkeypatch.setattr(a_stock, "_em_get", fake_get)
    return calls


def test_fund_flow_drops_rows_after_analysis_date(fake_em):
    out = a_stock.get_fund_flow("600519", PAST)

    assert "2099-01-01" not in out, "分析日之后的资金流泄漏了（未来函数）"
    assert PAST in out


def test_fund_flow_skips_realtime_when_historical(fake_em):
    a_stock.get_fund_flow("600519", PAST)

    assert not any("push2.eastmoney.com/api/qt/stock/fflow/kline" in u for u in fake_em), (
        "复盘历史日期时不该再去取今天的分钟资金流"
    )


def test_fund_flow_says_why_realtime_is_missing(fake_em):
    """略去实时段要说明原因，否则用户以为接口坏了。"""
    out = a_stock.get_fund_flow("600519", PAST)

    assert "略去实时分钟资金流" in out


def test_fund_flow_keeps_realtime_for_today(fake_em):
    """当天分析仍然要有实时资金流——防护不能误伤正常用法。"""
    a_stock.get_fund_flow("600519", TODAY)

    assert any("fflow/kline" in u for u in fake_em)


# ---------------------------------------------------------------------------
# 只有实时快照的两个：补不上就必须明说
# ---------------------------------------------------------------------------


def test_fundamentals_warns_on_historical_date(monkeypatch):
    monkeypatch.setattr(a_stock, "_tencent_quote", lambda codes: {})
    monkeypatch.setattr(a_stock, "_mootdx_call", lambda *a, **k: None)
    monkeypatch.setattr(a_stock, "_em_get", lambda *a, **k: FakeResp({}))

    out = a_stock.get_fundamentals("600519", PAST)

    assert "未来函数警告" in out
    assert PAST in out


def test_fundamentals_silent_for_today(monkeypatch):
    monkeypatch.setattr(a_stock, "_tencent_quote", lambda codes: {})
    monkeypatch.setattr(a_stock, "_mootdx_call", lambda *a, **k: None)
    monkeypatch.setattr(a_stock, "_em_get", lambda *a, **k: FakeResp({}))

    out = a_stock.get_fundamentals("600519", TODAY)

    assert "未来函数警告" not in out


def test_profit_forecast_warns_on_historical_date(monkeypatch):
    import pandas as pd

    monkeypatch.setattr(
        a_stock, "_ths_eps_forecast",
        lambda code: pd.DataFrame({"年度": ["2026"], "预测每股收益": [1.23]}),
    )

    out = a_stock.get_profit_forecast("600519", PAST)

    assert "未来函数警告" in out
