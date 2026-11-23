"""Indicatori e regole Donchian20 + Walking on the Upper Band."""
from __future__ import annotations
import pandas as pd

def add_indicators(frame: pd.DataFrame, config: dict) -> pd.DataFrame:
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(frame.columns):
        raise ValueError(f"OHLC columns missing: {sorted(required - set(frame.columns))}")
    df = frame.copy().sort_index()
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    n_atr = int(config["atr_period"])
    df["ATR14"] = tr.ewm(alpha=1/n_atr, adjust=False, min_periods=n_atr).mean()
    n = int(config["donchian_period"])
    df["DONCHIAN20_UPPER"] = df["High"].shift(1).rolling(n, min_periods=n).max()
    bb_n = int(config["bollinger_period"])
    df["BB_MID"] = df["Close"].rolling(bb_n, min_periods=bb_n).mean()
    std = df["Close"].rolling(bb_n, min_periods=bb_n).std(ddof=1)
    df["BB_UPPER"] = df["BB_MID"] + float(config["bollinger_std"]) * std
    df["WALKING_BAR"] = (
        (df["BB_UPPER"].notna()) &
        (df["BB_UPPER"].shift(1).notna()) &
        (df["Close"] >= df["BB_UPPER"] * (1-float(config["walking_tolerance"]))) &
        (df["Close"] >= df["BB_MID"]) &
        (df["BB_UPPER"] > df["BB_UPPER"].shift(1))
    )
    w = int(config["walking_window"])
    required_w = int(config["walking_required_bars"])
    df["WALKING_COUNT_3"] = df["WALKING_BAR"].rolling(w, min_periods=w).sum()
    df["WALKING"] = df["WALKING_COUNT_3"].ge(required_w).fillna(False)
    df["DONCHIAN_BREAKOUT"] = (df["Close"] > df["DONCHIAN20_UPPER"]).fillna(False)
    df["ENTRY_SIGNAL"] = df["DONCHIAN_BREAKOUT"] & df["WALKING"] & df["ATR14"].notna() & (df["ATR14"] > 0)
    return df

def entry_reason(row) -> str:
    return (f"Close {row.Close:.4f} sopra Donchian20 {row.DONCHIAN20_UPPER:.4f}; "
            f"Walking attivo ({int(row.WALKING_COUNT_3)}/3 ultime sedute); "
            f"ATR14 {row.ATR14:.4f}.")
