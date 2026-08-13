import pandas as pd

from tradingagents.dataflows import a_stock


def test_ths_eps_forecast_parses_response_body_as_html(monkeypatch):
    html = """
    <table>
      <thead><tr><th>年度</th><th>预测机构数</th><th>最小值</th><th>均值</th><th>最大值</th></tr></thead>
      <tbody><tr><td>2026</td><td>12</td><td>20.0</td><td>22.5</td><td>25.0</td></tr></tbody>
    </table>
    """

    class Response:
        text = html
        encoding = None

    monkeypatch.setattr(a_stock._requests, "get", lambda *args, **kwargs: Response())

    result = a_stock._ths_eps_forecast("300308")

    assert isinstance(result, pd.DataFrame)
    assert result.iloc[0]["年度"] == 2026
    assert result.iloc[0]["均值"] == 22.5
