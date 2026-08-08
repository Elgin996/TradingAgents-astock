"""F1.1 — parse_rating negation, compound nouns, label precedence."""

import pytest

from tradingagents.agents.utils.rating import parse_rating


@pytest.mark.parametrize("text,expected", [
    # --- existing 8, unchanged ---
    ("We would not buy this stock at these levels.", "Hold"),
    ("不建议卖出，继续观察。", "Hold"),
    ("大股东减持压力较大，但基本面稳健。", "Hold"),
    ("龙虎榜卖出席位以游资为主。", "Hold"),
    ("Rating: Sell\nWe would not buy this stock.", "Sell"),
    ("最终评级：卖出", "Sell"),
    ("综合来看，我们给予买入评级。", "Buy"),
    ("The bear case is strong; we sell.\n\nRating: Hold", "Hold"),

    # --- R1: 不 inside a positive compound must NOT negate ---
    ("公司基本面不错，我们给予买入评级。", "Buy"),
    ("营收增长不俗，维持买入。", "Buy"),
    ("风险不小，但我们仍建议买入。", "Buy"),
    ("不仅估值合理，且景气度向上，给予买入。", "Buy"),
    ("公司订单不断增加，给予买入。", "Buy"),
    ("短期波动不少，长期给予增持。", "Overweight"),

    # --- genuine negation must still negate ---
    ("我们不看好该标的，不建议买入。", "Hold"),
    ("估值已高，不宜买入。", "Hold"),
    ("We cannot buy at this price.", "Hold"),

    # --- 'not' must not match inside a longer word ---
    ("Nothing here is notable; we buy.", "Buy"),

    # --- compound nouns, both directions ---
    ("买入席位为机构专用，卖出席位为游资。", "Hold"),
    ("大股东拟减持不超过2%股份，我们维持买入评级。", "Buy"),
    ("减持计划已完成，基本面改善，给予增持。", "Overweight"),
    ("北向买入居前，但估值偏高，建议减持。", "Underweight"),

    # --- clause scoping: a cue must not cross ，---
    ("我们建议买入，而非卖出。", "Buy"),

    # --- labels and ordering ---
    ("估值偏高，建议卖出。", "Sell"),
    ("buy\nsomething else\nsell\n", "Sell"),
    ("Rating: BUY\n", "Buy"),
    ("投资建议：买入", "Buy"),
    ("", "Hold"),
])
def test_parse_rating(text, expected):
    assert parse_rating(text) == expected
