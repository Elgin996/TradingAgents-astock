"""Persistent local master data for instruments that completed an analysis."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _database_path(data_cache_dir: str | Path) -> Path:
    return Path(data_cache_dir) / "instrument_master.sqlite3"


def _connect(data_cache_dir: str | Path) -> sqlite3.Connection:
    path = _database_path(data_cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS instruments (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            security_type TEXT NOT NULL,
            exchange TEXT,
            analysis_product TEXT,
            profile_json TEXT NOT NULL,
            last_analysis_date TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    return connection


def _clean_name(value: Any) -> str | None:
    name = "".join(ch for ch in str(value or "") if ch.isprintable()).strip()
    return name or None


def _name_from_state(symbol: str, profile: dict[str, Any], state: dict[str, Any]) -> str | None:
    for value in (
        profile.get("name"),
        profile.get("fund_name"),
        state.get("stock_name"),
        state.get("company_name"),
    ):
        name = _clean_name(value)
        if name and name != symbol:
            return name

    # Completed reports consistently render the subject as ``code name``.
    # This fallback also upgrades older stock profiles whose ``name`` was null.
    pattern = re.compile(
        rf"(?<!\d){re.escape(symbol)}\s+([^\s，。；：:、（）()|]{{2,24}})"
    )
    for key in (
        "market_report",
        "fundamentals_report",
        "news_report",
        "final_trade_decision",
    ):
        text = state.get(key)
        if not isinstance(text, str):
            continue
        match = pattern.search(text)
        if match:
            candidate = _clean_name(match.group(1))
            if candidate and not any(
                marker in candidate
                for marker in ("技术", "分析", "报告", "当前", "最新", "最终")
            ):
                return candidate.strip("`*_[]【】") or None
    return None


def save_completed_instrument(
    data_cache_dir: str | Path,
    symbol: str,
    analysis_mode: str,
    profile: dict[str, Any] | None,
    state: dict[str, Any],
    analysis_date: str,
) -> None:
    """Upsert basic stock/ETF identity after a successful completed run."""
    normalized_symbol = str(symbol).strip().upper()
    existing = get_instrument(data_cache_dir, normalized_symbol)
    frozen = dict((existing or {}).get("profile") or {})
    frozen.update(profile or {})
    security_type = str(frozen.get("security_type") or analysis_mode or "stock")
    if security_type not in {"stock", "etf"}:
        return
    name = _name_from_state(normalized_symbol, frozen, state) or (existing or {}).get("name")
    if name:
        frozen["name"] = name
        if security_type == "etf" and not frozen.get("fund_name"):
            frozen["fund_name"] = name
    frozen.setdefault("symbol", normalized_symbol)
    frozen.setdefault("security_type", security_type)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with _connect(data_cache_dir) as connection:
        connection.execute(
            """
            INSERT INTO instruments (
                symbol, name, security_type, exchange, analysis_product,
                profile_json, last_analysis_date, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name = COALESCE(excluded.name, instruments.name),
                security_type = excluded.security_type,
                exchange = COALESCE(excluded.exchange, instruments.exchange),
                analysis_product = COALESCE(excluded.analysis_product, instruments.analysis_product),
                profile_json = excluded.profile_json,
                last_analysis_date = excluded.last_analysis_date,
                updated_at = excluded.updated_at
            """,
            (
                normalized_symbol,
                name,
                security_type,
                frozen.get("exchange"),
                frozen.get("analysis_product") or state.get("analysis_product"),
                json.dumps(frozen, ensure_ascii=False, default=str),
                str(analysis_date),
                now,
            ),
        )


def get_instrument(data_cache_dir: str | Path, symbol: str) -> dict[str, Any] | None:
    """Return a saved instrument record, or ``None`` before its first completion."""
    path = _database_path(data_cache_dir)
    if not path.exists():
        return None
    try:
        with _connect(data_cache_dir) as connection:
            row = connection.execute(
                """
                SELECT name, security_type, exchange, analysis_product,
                       profile_json, last_analysis_date, updated_at
                FROM instruments WHERE symbol = ?
                """,
                (str(symbol).strip().upper(),),
            ).fetchone()
    except (sqlite3.Error, OSError):
        return None
    if row is None:
        return None
    try:
        profile = json.loads(row[4])
    except (TypeError, json.JSONDecodeError):
        profile = {}
    return {
        "symbol": str(symbol).strip().upper(),
        "name": row[0],
        "security_type": row[1],
        "exchange": row[2],
        "analysis_product": row[3],
        "profile": profile if isinstance(profile, dict) else {},
        "last_analysis_date": row[5],
        "updated_at": row[6],
    }


def find_instrument_by_name(data_cache_dir: str | Path, name: str) -> dict[str, Any] | None:
    """Resolve an exact locally saved stock/ETF name without a network lookup."""
    path = _database_path(data_cache_dir)
    clean = _clean_name(name)
    if not path.exists() or not clean:
        return None
    try:
        with _connect(data_cache_dir) as connection:
            row = connection.execute(
                "SELECT symbol FROM instruments WHERE name = ? LIMIT 1", (clean,)
            ).fetchone()
    except (sqlite3.Error, OSError):
        return None
    return get_instrument(data_cache_dir, row[0]) if row else None
