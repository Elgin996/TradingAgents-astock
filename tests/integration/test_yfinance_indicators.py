"""Live yfinance indicator smoke test — excluded from default CI."""

import time

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.integration
def test_yfinance_indicators_window():
    from tradingagents.dataflows.y_finance import get_stock_stats_indicators_window

    print("Testing optimized implementation with 30-day lookback:")
    start_time = time.time()
    result = get_stock_stats_indicators_window("AAPL", "macd", "2024-11-01", 30)
    end_time = time.time()

    print(f"Execution time: {end_time - start_time:.2f} seconds")
    print(f"Result length: {len(result)} characters")
    print(result)
    assert result


if __name__ == "__main__":
    test_yfinance_indicators_window()
