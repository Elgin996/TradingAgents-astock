"""Versioned, network-free technical indicator calculations."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from tradingagents.dataflows.models import IndicatorValue, NormalizedBar
from tradingagents.dataflows.config import load_project_versioned_config


INDICATOR_ENGINE_VERSION = "technical-indicators-v1"


class IndicatorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "indicator-config-v1"
    sma_periods: tuple[int, ...] = (20, 50, 200)
    ema_period: int = 10
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    boll_period: int = 20
    boll_std: float = 2.0
    atr_period: int = 14
    vwma_period: int = 20
    mfi_period: int = 14
    volume_short_period: int = 5
    volume_long_period: int = 20
    level_short_period: int = 20
    level_long_period: int = 60
    warmup_buffer: int = 20

    def required_warmup(self) -> int:
        return max(
            *self.sma_periods,
            self.macd_slow + self.macd_signal,
            self.rsi_period,
            self.boll_period,
            self.atr_period,
            self.vwma_period,
            self.mfi_period,
            self.volume_long_period,
            self.level_long_period,
        ) + self.warmup_buffer


def load_indicator_config() -> IndicatorConfig:
    """Build the runtime indicator configuration from its versioned file."""
    return IndicatorConfig.model_validate(
        load_project_versioned_config("indicator_config_v1.yaml")
    )


def _frame_from_bars(bars: Sequence[NormalizedBar | Mapping] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(bars, pd.DataFrame):
        frame = bars.copy()
    else:
        rows = [bar.model_dump() if isinstance(bar, NormalizedBar) else dict(bar) for bar in bars]
        frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["trade_date", "open", "high", "low", "close", "volume", "amount"])
    aliases = {
        "Date": "trade_date",
        "date": "trade_date",
        "datetime": "trade_date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "Amount": "amount",
    }
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})
    if "trade_date" not in frame:
        raise ValueError("indicator input requires trade_date/Date")
    required = {"open", "high", "low", "close"} - set(frame.columns)
    if required:
        raise ValueError(f"indicator input missing columns: {sorted(required)}")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column not in frame:
            frame[column] = pd.NA
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["trade_date", "open", "high", "low", "close"])
    frame = frame.sort_values("trade_date").drop_duplicates("trade_date", keep="first").reset_index(drop=True)
    return frame


def calculate_indicator_frame(
    bars: Sequence[NormalizedBar | Mapping] | pd.DataFrame,
    config: IndicatorConfig | None = None,
) -> pd.DataFrame:
    """Calculate all v1 indicators from an already-frozen bar sequence."""
    config = config or load_indicator_config()
    frame = _frame_from_bars(bars)
    if frame.empty:
        return frame
    close = frame["close"]
    high, low, volume = frame["high"], frame["low"], frame["volume"]
    for period in config.sma_periods:
        frame[f"close_sma_{period}"] = close.rolling(period, min_periods=period).mean()
    frame[f"close_{config.ema_period}_ema"] = close.ewm(span=config.ema_period, adjust=False, min_periods=config.ema_period).mean()
    ema_fast = close.ewm(span=config.macd_fast, adjust=False, min_periods=config.macd_fast).mean()
    ema_slow = close.ewm(span=config.macd_slow, adjust=False, min_periods=config.macd_slow).mean()
    frame["macd"] = ema_fast - ema_slow
    frame["macds"] = frame["macd"].ewm(span=config.macd_signal, adjust=False, min_periods=config.macd_signal).mean()
    frame["macdh"] = frame["macd"] - frame["macds"]
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / config.rsi_period, adjust=False, min_periods=config.rsi_period).mean()
    avg_loss = loss.ewm(alpha=1 / config.rsi_period, adjust=False, min_periods=config.rsi_period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    frame["rsi"] = (100 - (100 / (1 + rs))).where(avg_loss != 0, 100.0)
    middle = close.rolling(config.boll_period, min_periods=config.boll_period).mean()
    std = close.rolling(config.boll_period, min_periods=config.boll_period).std(ddof=0)
    frame["boll"] = middle
    frame["boll_ub"] = middle + config.boll_std * std
    frame["boll_lb"] = middle - config.boll_std * std
    previous_close = close.shift(1)
    true_range = pd.concat([high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    frame["atr"] = true_range.ewm(alpha=1 / config.atr_period, adjust=False, min_periods=config.atr_period).mean()
    frame["vwma"] = (close * volume).rolling(config.vwma_period, min_periods=config.vwma_period).sum() / volume.rolling(config.vwma_period, min_periods=config.vwma_period).sum().replace(0, pd.NA)
    typical = (high + low + close) / 3
    raw_flow = typical * volume
    direction = typical.diff()
    positive_flow = raw_flow.where(direction > 0, 0.0)
    negative_flow = raw_flow.where(direction < 0, 0.0).abs()
    money_ratio = positive_flow.rolling(config.mfi_period, min_periods=config.mfi_period).sum() / negative_flow.rolling(config.mfi_period, min_periods=config.mfi_period).sum().replace(0, pd.NA)
    frame["mfi"] = (100 - (100 / (1 + money_ratio))).where(volume.notna())
    frame[f"volume_{config.volume_short_period}_sma"] = volume.rolling(config.volume_short_period, min_periods=config.volume_short_period).mean()
    frame[f"volume_{config.volume_long_period}_sma"] = volume.rolling(config.volume_long_period, min_periods=config.volume_long_period).mean()
    frame[f"rolling_high_{config.level_short_period}"] = close.shift(1).rolling(config.level_short_period, min_periods=config.level_short_period).max()
    frame[f"rolling_low_{config.level_short_period}"] = close.shift(1).rolling(config.level_short_period, min_periods=config.level_short_period).min()
    frame[f"rolling_high_{config.level_long_period}"] = close.shift(1).rolling(config.level_long_period, min_periods=config.level_long_period).max()
    frame[f"rolling_low_{config.level_long_period}"] = close.shift(1).rolling(config.level_long_period, min_periods=config.level_long_period).min()
    numeric_columns = frame.select_dtypes(include="number").columns
    frame[numeric_columns] = frame[numeric_columns].replace([float("inf"), float("-inf")], pd.NA)
    return frame


class IndicatorEngine:
    """Pure wrapper that makes the calculation and version explicit."""

    engine_version = INDICATOR_ENGINE_VERSION

    def __init__(self, config: IndicatorConfig | None = None):
        self.config = config or load_indicator_config()

    def calculate_frame(self, bars, *, display_start: date | None = None) -> pd.DataFrame:
        frame = calculate_indicator_frame(bars, self.config)
        if display_start is not None:
            frame = frame[frame["trade_date"].dt.date >= display_start].copy()
        return frame

    def calculate(self, bars, *, display_start: date | None = None) -> dict[str, list[IndicatorValue]]:
        frame = calculate_indicator_frame(bars, self.config)
        if display_start is not None:
            frame = frame[frame["trade_date"].dt.date >= display_start]
        ignored = {"trade_date", "open", "high", "low", "close", "volume", "amount"}
        output: dict[str, list[IndicatorValue]] = {}
        for name in (column for column in frame.columns if column not in ignored):
            required = self._required_period(name)
            output[name] = [
                IndicatorValue(
                    name=name,
                    value=None if pd.isna(value) else float(value),
                    trade_date=timestamp.date(),
                    parameters={"period": required},
                    warmup_complete=not pd.isna(value) and len(frame.loc[:index, name].dropna()) >= 1,
                    engine_version=self.engine_version,
                )
                for index, (timestamp, value) in enumerate(zip(frame["trade_date"], frame[name]))
            ]
        return output

    @staticmethod
    def _required_period(name: str) -> int:
        digits = [int(part) for part in name.split("_") if part.isdigit()]
        return max(digits or [1])


def calculate_indicators(bars, config: IndicatorConfig | None = None):
    return IndicatorEngine(config).calculate(bars)
