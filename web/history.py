"""Manage completed and incomplete analysis history."""

from __future__ import annotations

import json
import logging
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG


logger = logging.getLogger(__name__)

# Keep web history alongside the configured report directory.  This is normally
# ~/.tradingagents, but users may redirect all runtime data with the
# TRADINGAGENTS_* environment variables.
_INCOMPLETE_TASKS_FILE = Path(DEFAULT_CONFIG["results_dir"]).parent / "incomplete_tasks.json"
_INCOMPLETE_TASKS_LOCK = threading.Lock()


def _results_dir() -> Path:
    """Return the configured report directory, not a hard-coded home path."""
    return Path(DEFAULT_CONFIG["results_dir"])


def _load_state(path: str | Path, date: str) -> dict[str, Any]:
    """Load a saved analysis JSON file, tolerating both on-disk shapes.

    The production writer (``TradingAgentsGraph._log_state``) dumps the state
    dict directly (flat). Some historical logs nested it one level under the
    trade-date string. Try the flat shape first; fall back to the nested
    lookup only when the top-level payload does not look like a state dict.
    """
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return {}
    inner = payload.get(date)
    if isinstance(inner, dict):
        return inner
    return payload


def get_history() -> list[dict[str, str]]:
    """Scan saved analysis logs and return a sorted list (newest first).

    Each entry: {"ticker", "date", "path", optional product identity and
    snapshot fields} when present in the saved state. Legacy logs remain
    readable and are not reclassified.
    """
    root = _results_dir()
    if not root.exists():
        return []

    entries: list[dict[str, Any]] = []
    for log_file in root.rglob("full_states_log_*.json"):
        match = re.search(r"full_states_log_(\d{4}-\d{2}-\d{2})\.json$", log_file.name)
        if not match:
            continue
        date = match.group(1)
        ticker = log_file.parent.parent.name
        entry: dict[str, Any] = {"ticker": ticker, "date": date, "path": str(log_file)}
        try:
            state = _load_state(log_file, date)
            entry["analysis_mode"] = state.get("analysis_mode", "stock")
            for key in (
                "analysis_product",
                "instrument_profile",
                "market_snapshot_id",
                "analysis_market_data_bundle",
                "product_technical_evidence_bundle",
                "technical_shadow_comparison",
            ):
                if state.get(key):
                    entry[key] = state.get(key)
        except (OSError, json.JSONDecodeError, TypeError):
            entry["analysis_mode"] = "stock"
        entries.append(entry)

    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


def _completed_key(ticker: str, trade_date: str) -> tuple[str, str]:
    return ticker.upper(), trade_date


def _incomplete_key(
    ticker: str,
    trade_date: str,
    analysis_mode: str = "stock",
    analysis_product: str | None = None,
) -> tuple[str, str, str, str]:
    return ticker.upper(), trade_date, analysis_mode, analysis_product or "legacy"


def _completed_keys() -> set[tuple[str, str]]:
    return {
        _completed_key(entry["ticker"], entry["date"])
        for entry in get_history()
    }


def _load_incomplete_index() -> list[dict[str, Any]]:
    if not _INCOMPLETE_TASKS_FILE.exists():
        return []

    try:
        with open(_INCOMPLETE_TASKS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    entries: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).strip().upper()
        trade_date = str(item.get("trade_date", "")).strip()
        if not ticker or not re.match(r"^\d{4}-\d{2}-\d{2}$", trade_date):
            continue
        item["ticker"] = ticker
        item["trade_date"] = trade_date
        entries.append(item)
    return entries


def _save_incomplete_index(entries: list[dict[str, Any]]) -> None:
    """原子写 incomplete_tasks.json，兼容 Windows 文件占用。

    目标文件可能被其他进程短暂占用（如多实例 Web UI、杀毒软件扫描），
    此时 ``tmp.replace`` 在 Windows 上会抛 ``PermissionError``（#77）。
    先重试几次等待锁释放，仍失败则降级为直接覆写——读取端
    （``_load_incomplete_index``）已容错损坏 JSON，索引写不进去不致命。
    """
    parent = _INCOMPLETE_TASKS_FILE.parent
    parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(entries, ensure_ascii=False, indent=2)

    for attempt in range(3):
        tmp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=parent,
                prefix=f"{_INCOMPLETE_TASKS_FILE.stem}.",
                suffix=".tmp",
                delete=False,
            ) as f:
                f.write(payload)
                tmp = Path(f.name)
            tmp.replace(_INCOMPLETE_TASKS_FILE)
            return
        except PermissionError:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
            if attempt < 2:
                # 锁通常是瞬时的，短暂等待后重试
                time.sleep(0.15 * (attempt + 1))
        except OSError:
            raise

    # 重试耗尽仍被占用：直接覆写（非原子但可接受）。
    try:
        _INCOMPLETE_TASKS_FILE.write_text(payload, encoding="utf-8")
    except OSError as e:
        # 索引写不进去不致命——读取端容错、下次写入会自动重建，所以不往上抛。
        # 但**不能一声不吭**：完全静默的话，用户永远不会知道它一直在失败，
        # 「未完成任务」列表长期不更新时也无从排查。
        logger.warning(
            "写入未完成任务索引失败（已重试并降级为直接覆写）：%s。"
            "不影响本次分析，但侧边栏的未完成任务列表可能不是最新的。", e
        )


def _checkpoint_step(
    ticker: str,
    trade_date: str,
    analysis_mode: str = "stock",
    analysis_product: str | None = None,
) -> int | None:
    try:
        from tradingagents.graph.checkpointer import checkpoint_step

        return checkpoint_step(
            DEFAULT_CONFIG["data_cache_dir"],
            ticker,
            trade_date,
            analysis_mode,
            report_schema_version=(f"{analysis_product}-v2" if analysis_product else None),
        )
    except Exception:
        return None


def record_incomplete_task(
    ticker: str,
    trade_date: str,
    *,
    status: str,
    error: str | None = None,
    completed_stages: list[str] | None = None,
    analysis_mode: str = "stock",
    analysis_product: str | None = None,
    instrument_profile: dict[str, Any] | None = None,
) -> None:
    """Upsert a resumable task entry."""
    ticker = ticker.strip().upper()
    trade_date = trade_date.strip()
    if not ticker or not trade_date:
        return

    with _INCOMPLETE_TASKS_LOCK:
        entries = [
            entry
            for entry in _load_incomplete_index()
            if _incomplete_key(
                entry["ticker"],
                entry["trade_date"],
                entry.get("analysis_mode", "stock"),
                entry.get("analysis_product"),
            )
            != _incomplete_key(ticker, trade_date, analysis_mode, analysis_product)
        ]
        now = time.time()
        entry = {
            "ticker": ticker,
            "trade_date": trade_date,
            "status": status,
            "error": error or "",
            "completed_stages": completed_stages or [],
            "analysis_mode": analysis_mode,
            "instrument_profile": instrument_profile,
            "updated_at": now,
        }
        if analysis_product is not None:
            entry["analysis_product"] = analysis_product
        entries.append(entry)
        entries.sort(key=lambda e: float(e.get("updated_at", 0)), reverse=True)
        _save_incomplete_index(entries)


def clear_incomplete_task(
    ticker: str,
    trade_date: str,
    analysis_mode: str = "stock",
    analysis_product: str | None = None,
) -> None:
    """Remove an incomplete task once it completes successfully."""
    ticker = ticker.strip().upper()
    trade_date = trade_date.strip()
    with _INCOMPLETE_TASKS_LOCK:
        entries = [
            entry
            for entry in _load_incomplete_index()
            if _incomplete_key(
                entry["ticker"],
                entry["trade_date"],
                entry.get("analysis_mode", "stock"),
                entry.get("analysis_product"),
            )
            != _incomplete_key(ticker, trade_date, analysis_mode, analysis_product)
        ]
        _save_incomplete_index(entries)


def get_incomplete_history() -> list[dict[str, Any]]:
    """Return unfinished tasks that can be resumed from their checkpoint."""
    completed = _completed_keys()
    active_entries: list[dict[str, Any]] = []

    with _INCOMPLETE_TASKS_LOCK:
        entries = _load_incomplete_index()
        for entry in entries:
            key = _completed_key(entry["ticker"], entry["trade_date"])
            if key in completed:
                continue

            product = entry.get("analysis_product")
            if product:
                step = _checkpoint_step(
                    entry["ticker"],
                    entry["trade_date"],
                    entry.get("analysis_mode", "stock"),
                    product,
                )
            else:
                # Preserve compatibility with callers/tests that provide the
                # legacy three-argument checkpoint helper.
                step = _checkpoint_step(
                    entry["ticker"],
                    entry["trade_date"],
                    entry.get("analysis_mode", "stock"),
                )
            entry["checkpoint_step"] = step
            active_entries.append(entry)

        active_entries.sort(key=lambda e: float(e.get("updated_at", 0)), reverse=True)
        if len(active_entries) != len(entries):
            _save_incomplete_index(active_entries)
    return active_entries


def load_analysis(path: str) -> dict[str, Any]:
    """Load a saved analysis JSON file, tolerating flat or nested shapes."""
    match = re.search(r"full_states_log_(\d{4}-\d{2}-\d{2})\.json$", Path(path).name)
    date = match.group(1) if match else ""
    return _load_state(path, date)


def extract_signal(state: dict[str, Any]) -> str:
    """Extract the 5-tier rating from a final state dict for history reload.

    Delegates to the shared ``parse_rating`` heuristic so the history-reload
    display matches the live signal (``TradingAgentsGraph.process_signal``) and
    understands Chinese free-text decisions — not just English keywords. The
    old English-only ``BUY/SELL/HOLD`` scan silently returned Hold/N/A for
    every Chinese-output run (issues #78 / #80). ``final_trade_decision`` is
    checked first so the reload matches the authoritative live signal.
    """
    import re

    from tradingagents.agents.utils.rating import parse_rating

    _UNKNOWN = ""
    for field in (
        "final_trade_decision",
        "trader_investment_decision",
        "investment_plan",
    ):
        text = state.get(field, "")
        if not text:
            continue
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        rating = parse_rating(cleaned, default=_UNKNOWN)
        if rating:
            return rating
    return "N/A"
