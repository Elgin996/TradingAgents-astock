"""Tests for Web history helpers."""

from __future__ import annotations

import json
import threading

from web import history


def test_history_uses_configured_results_directory(tmp_path, monkeypatch):
    """Primary case: production writer dumps a flat state dict (no date wrapper)."""
    logs = tmp_path / "project-data" / "logs"
    log_dir = logs / "600370" / "TradingAgentsStrategy_logs"
    log_dir.mkdir(parents=True)
    (log_dir / "full_states_log_2026-06-02.json").write_text(
        json.dumps(
            {
                "final_trade_decision": "HOLD",
                "analysis_mode": "stock",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(history.DEFAULT_CONFIG, "results_dir", str(logs))

    assert history.get_history() == [
        {
            "ticker": "600370",
            "date": "2026-06-02",
            "path": str(log_dir / "full_states_log_2026-06-02.json"),
            "analysis_mode": "stock",
        }
    ]


def test_history_loads_etf_mode_badge_fields(tmp_path, monkeypatch):
    """Primary (flat) shape must surface analysis_mode/instrument_profile."""
    logs = tmp_path / "logs"
    log_dir = logs / "510300" / "TradingAgentsStrategy_logs"
    log_dir.mkdir(parents=True)
    (log_dir / "full_states_log_2026-08-08.json").write_text(
        json.dumps(
            {
                "analysis_mode": "etf",
                "instrument_profile": {
                    "fund_name": "华泰柏瑞沪深300ETF",
                    "tracking_index_name": "沪深300指数",
                },
                "final_trade_decision": "HOLD",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(history.DEFAULT_CONFIG, "results_dir", str(logs))

    entries = history.get_history()
    assert entries[0]["analysis_mode"] == "etf"
    assert entries[0]["instrument_profile"]["tracking_index_name"] == "沪深300指数"

    from web.components.sidebar import _history_mode_badge, _history_mode_label

    assert _history_mode_badge(entries[0]) == "[ETF]"
    assert _history_mode_label(entries[0]) == "[ETF] · 华泰柏瑞沪深300ETF"
    assert _history_mode_badge({"analysis_mode": "stock"}) == "[个股]"


def test_history_mode_label_does_not_fall_back_to_index_name():
    from web.components.sidebar import _history_mode_label

    entry = {
        "analysis_mode": "etf",
        "instrument_profile": {"tracking_index_name": "沪深300指数"},
    }
    assert _history_mode_label(entry) == "[ETF]"


def test_history_loads_legacy_nested_shape(tmp_path, monkeypatch):
    """Compatibility: some historical logs nested the state under the date key."""
    logs = tmp_path / "logs"
    log_dir = logs / "510300" / "TradingAgentsStrategy_logs"
    log_dir.mkdir(parents=True)
    (log_dir / "full_states_log_2026-08-08.json").write_text(
        json.dumps(
            {
                "2026-08-08": {
                    "analysis_mode": "etf",
                    "instrument_profile": {
                        "tracking_index_name": "沪深300指数",
                    },
                    "final_trade_decision": "HOLD",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(history.DEFAULT_CONFIG, "results_dir", str(logs))

    entries = history.get_history()
    assert entries[0]["analysis_mode"] == "etf"
    assert entries[0]["instrument_profile"]["tracking_index_name"] == "沪深300指数"


def test_load_analysis_reads_flat_shape(tmp_path):
    path = tmp_path / "full_states_log_2026-06-02.json"
    path.write_text(json.dumps({"final_trade_decision": "HOLD"}), encoding="utf-8")

    assert history.load_analysis(str(path)) == {"final_trade_decision": "HOLD"}


def test_load_analysis_reads_legacy_nested_shape(tmp_path):
    path = tmp_path / "full_states_log_2026-06-02.json"
    path.write_text(
        json.dumps({"2026-06-02": {"final_trade_decision": "SELL"}}),
        encoding="utf-8",
    )

    assert history.load_analysis(str(path)) == {"final_trade_decision": "SELL"}


def test_log_state_write_read_round_trip(tmp_path, monkeypatch):
    """End-to-end: TradingAgentsGraph._log_state writes what get_history reads.

    This is the real regression guard for the history-shape bug: a helper-only
    test could pass while the writer and reader still disagreed on shape.
    """
    from unittest.mock import MagicMock

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    mock_client = MagicMock()
    mock_client.get_llm.return_value = MagicMock()
    monkeypatch.setattr(
        "tradingagents.graph.trading_graph.create_llm_client",
        lambda **kwargs: mock_client,
    )

    logs = tmp_path / "logs"
    cfg = {
        **DEFAULT_CONFIG,
        "data_cache_dir": str(tmp_path / "cache"),
        "results_dir": str(logs),
        "memory_log_path": str(tmp_path / "memory.md"),
    }
    ta = TradingAgentsGraph(config=cfg, selected_analysts=["market"])
    ta.ticker = "510300"
    ta.analysis_mode = "etf"
    ta.instrument_profile = {"tracking_index_name": "沪深300指数"}

    ta._log_state(
        "2026-08-08",
        {
            "company_of_interest": "510300",
            "final_trade_decision": "HOLD",
            "data_quality_summary": "质量门控通过",
            "data_quality_failed": False,
        },
    )

    monkeypatch.setitem(history.DEFAULT_CONFIG, "results_dir", str(logs))
    entries = history.get_history()
    assert len(entries) == 1
    assert entries[0]["analysis_mode"] == "etf"
    assert entries[0]["instrument_profile"]["tracking_index_name"] == "沪深300指数"
    saved = history.load_analysis(entries[0]["path"])
    assert saved["data_quality_summary"] == "质量门控通过"
    assert saved["data_quality_failed"] is False


def test_incomplete_task_round_trip(tmp_path, monkeypatch):
    index = tmp_path / "incomplete_tasks.json"
    logs = tmp_path / "logs"
    monkeypatch.setattr(history, "_INCOMPLETE_TASKS_FILE", index)
    monkeypatch.setattr(history, "_results_dir", lambda: logs)
    monkeypatch.setattr(
        history, "_checkpoint_step", lambda ticker, trade_date, analysis_mode="stock": 3
    )

    history.record_incomplete_task(
        "600370",
        "2026-06-02",
        status="error",
        error="quota exceeded",
        completed_stages=["market", "news"],
        analysis_mode="etf",
        instrument_profile={
            "symbol": "510300",
            "tracking_index_code": "000300",
            "tracking_index_code_status": "user_supplied",
        },
    )

    entries = history.get_incomplete_history()

    assert entries == [
        {
            "ticker": "600370",
            "trade_date": "2026-06-02",
            "status": "error",
            "error": "quota exceeded",
            "completed_stages": ["market", "news"],
            "analysis_mode": "etf",
            "instrument_profile": {
                "symbol": "510300",
                "tracking_index_code": "000300",
                "tracking_index_code_status": "user_supplied",
            },
            "updated_at": entries[0]["updated_at"],
            "checkpoint_step": 3,
        }
    ]


def test_completed_history_hides_incomplete_task(tmp_path, monkeypatch):
    index = tmp_path / "incomplete_tasks.json"
    logs = tmp_path / "logs"
    log_dir = logs / "600370" / "TradingAgentsStrategy_logs"
    log_dir.mkdir(parents=True)
    (log_dir / "full_states_log_2026-06-02.json").write_text(
        json.dumps({"final_trade_decision": "HOLD"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(history, "_INCOMPLETE_TASKS_FILE", index)
    monkeypatch.setattr(history, "_results_dir", lambda: logs)
    monkeypatch.setattr(
        history, "_checkpoint_step", lambda ticker, trade_date, analysis_mode="stock": 3
    )

    history.record_incomplete_task("600370", "2026-06-02", status="running")

    assert history.get_incomplete_history() == []


def test_incomplete_task_writes_are_thread_safe(tmp_path, monkeypatch):
    index = tmp_path / "incomplete_tasks.json"
    logs = tmp_path / "logs"
    monkeypatch.setattr(history, "_INCOMPLETE_TASKS_FILE", index)
    monkeypatch.setattr(history, "_results_dir", lambda: logs)
    monkeypatch.setattr(
        history, "_checkpoint_step", lambda ticker, trade_date, analysis_mode="stock": 1
    )

    def write_task(i: int) -> None:
        history.record_incomplete_task(
            f"60037{i % 10}",
            "2026-06-02",
            status="running",
            completed_stages=["market"],
        )

    threads = [threading.Thread(target=write_task, args=(i,)) for i in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    entries = history.get_incomplete_history()

    assert len(entries) == 10
    assert {entry["status"] for entry in entries} == {"running"}
    assert not list(tmp_path.glob("*.tmp"))


def test_extract_signal_chinese_final_decision():
    """Chinese free-text decision must yield the real rating, not Hold/N/A.

    Regression for issues #78 / #80: history reload used an English-only
    BUY/SELL/HOLD scan that missed Chinese output entirely.
    """
    state = {
        "final_trade_decision": "最终评级：卖出\n核心结论：风险尚未出清。",
        "investment_plan": "研究经理倾向持有观望。",
    }
    assert history.extract_signal(state) == "Sell"


def test_extract_signal_prefers_final_trade_decision():
    """The reload signal must match the authoritative live signal source."""
    state = {
        "investment_plan": "最终评级：买入",
        "final_trade_decision": "最终评级：减持",
    }
    assert history.extract_signal(state) == "Underweight"


def test_extract_signal_english_still_works():
    state = {"final_trade_decision": "**Rating**: Buy\n\nThesis."}
    assert history.extract_signal(state) == "Buy"


def test_extract_signal_unknown_returns_na():
    assert history.extract_signal({"final_trade_decision": "无明确方向。"}) == "N/A"
    assert history.extract_signal({}) == "N/A"
