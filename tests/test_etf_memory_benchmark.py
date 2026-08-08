from tradingagents.agents.utils.memory import TradingMemoryLog


def test_etf_memory_preserves_tracking_index_for_future_reflection(tmp_path):
    log = TradingMemoryLog({"memory_log_path": str(tmp_path / "memory.md")})
    log.store_decision(
        "510300",
        "2026-08-07",
        "Rating: Hold",
        analysis_mode="etf",
        tracking_index_code="000300",
        tracking_index_name="沪深300",
    )

    entry = log.get_pending_entries()[0]

    assert entry["analysis_mode"] == "etf"
    assert entry["tracking_index_code"] == "000300"
    assert entry["tracking_index_name"] == "沪深300"


def test_etf_memory_does_not_mix_cross_index_lessons(tmp_path):
    log = TradingMemoryLog({"memory_log_path": str(tmp_path / "memory.md")})
    log.store_decision(
        "510300", "2026-08-01", "Rating: Hold",
        analysis_mode="etf", tracking_index_code="000300",
    )
    log.store_decision(
        "159915", "2026-08-02", "Rating: Buy",
        analysis_mode="etf", tracking_index_code="399006",
    )
    log.update_with_outcome(
        "510300", "2026-08-01", 0.01, 0.001, 5, "Tracked index lesson."
    )
    log.update_with_outcome(
        "159915", "2026-08-02", 0.02, 0.002, 5, "Other index lesson."
    )

    context = log.get_past_context(
        "510300",
        analysis_mode="etf",
        tracking_index_code="000300",
    )

    assert "510300" in context
    assert "159915" not in context
