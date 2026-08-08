"""F1.1 — parse_rating negation, compound nouns, label precedence."""

import pytest

from tradingagents.agents.utils.rating import parse_rating


@pytest.mark.parametrize("text,expected", [
    ("We would not buy this stock at these levels.", "Hold"),
    ("不建议卖出，继续观察。", "Hold"),
    ("大股东减持压力较大，但基本面稳健。", "Hold"),
    ("龙虎榜卖出席位以游资为主。", "Hold"),
    ("Rating: Sell\nWe would not buy this stock.", "Sell"),   # label wins
    ("最终评级：卖出", "Sell"),
    ("综合来看，我们给予买入评级。", "Buy"),                    # bare term still works
    ("The bear case is strong; we sell.\n\nRating: Hold", "Hold"),
])
def test_parse_rating(text, expected):
    assert parse_rating(text) == expected
