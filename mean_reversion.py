"""Independent mean-reversion research engine; never shares TF signals or positions."""
from __future__ import annotations
import math
import pandas as pd

def add_mr_indicators(frame: pd.DataFrame, config: dict) -> pd.DataFrame:
    df = frame.copy().sort_index()
    close = pd.to_numeric(df["Close"], errors="coerce")
    prev_close = close.shift(1)
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr_period = int(config.get("atr_period", 14))
    df["ATR14"] = tr.ewm(alpha=1/atr_period, adjust=False, min_periods=atr_period).mean()
    n = int(config.get("mr_bollinger_period", 20))
    mult = float(config.get("mr_bollinger_std", 2.0))
    df["MR_BB_MID"] = close.rolling(n, min_periods=n).mean()
    sd = close.rolling(n, min_periods=n).std(ddof=1)
    df["MR_BB_LOWER"] = df["MR_BB_MID"] - mult * sd
    delta = close.diff()
    gains = delta.clip(lower=0).rolling(2, min_periods=2).mean()
    losses = (-delta.clip(upper=0)).rolling(2, min_periods=2).mean()
    rs = gains / losses.replace(0, float("nan"))
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.mask((losses == 0) & (gains > 0), 100)
    rsi = rsi.mask((losses == 0) & (gains == 0), 50)
    df["MR_RSI2"] = rsi
    threshold = float(config.get("mr_rsi_entry", 10))
    # Classic oversold mean-reversion entry: buy only after a completed
    # close below the lower band with RSI(2) <= threshold; fill next session open.
    below = close.le(df["MR_BB_LOWER"])
    oversold = df["MR_RSI2"].le(threshold)
    df["MR_ENTRY_SIGNAL"] = (below & oversold & df["MR_BB_MID"].notna()).fillna(False)
    return df

def _finish(symbol, instrument, pos, date, price, reason, config):
    gross = (float(price) / pos["entry_price"] - 1) * 100
    row = {
        "strategy": "MEAN_REVERSION", "symbol": symbol,
        "name": instrument.get("name", symbol), "category": instrument["classification"],
        "signal_date": pos["signal_date"], "entry_date": pos["entry_date"],
        "entry_price": round(pos["entry_price"], 8), "exit_date": date,
        "exit_price": round(float(price), 8), "holding_sessions": pos["holding_sessions"],
        "exit_reason": reason, "gross_return_pct": round(gross, 5)
    }
    for bps in config["costs_bps_round_trip"]:
        row[f"net_{bps}bps_pct"] = round(gross - float(bps) / 100, 5)
    return row

def simulate_mr(symbol, instrument, frame, config):
    df = add_mr_indicators(frame, config)
    trades, pos, pending = [], None, None
    stop_multiple = float(config.get("mr_atr_stop_multiple", 2.0))
    max_days = int(config.get("mr_max_holding_sessions", 10))
    for date, row in df.iterrows():
        day = str(pd.Timestamp(date).date())
        op, hi, lo, close = (float(row[x]) for x in ("Open", "High", "Low", "Close"))
        if not all(math.isfinite(x) and x > 0 for x in (op, hi, lo, close)):
            continue
        if pending is not None and pos is None:
            atr = float(pending["atr"])
            pos = {"signal_date": pending["date"], "entry_date": day,
                   "entry_price": op, "stop_price": op - stop_multiple * atr,
                   "holding_sessions": 0}
            pending = None
        if pos is not None:
            pos["holding_sessions"] += 1
            if lo <= pos["stop_price"]:
                fill = op if op < pos["stop_price"] else pos["stop_price"]
                trades.append(_finish(symbol, instrument, pos, day, fill, "ATR14_X2_STOP", config))
                pos = None
                continue
            mid = row.get("MR_BB_MID")
            if pd.notna(mid) and close >= float(mid):
                trades.append(_finish(symbol, instrument, pos, day, close, "BB_MID_REVERSION", config))
                pos = None
                continue
            if pos["holding_sessions"] >= max_days:
                trades.append(_finish(symbol, instrument, pos, day, close, "MAX_HOLDING_SESSIONS", config))
                pos = None
                continue
        if pos is None and pending is None and bool(row.get("MR_ENTRY_SIGNAL", False)):
            atr = row.get("ATR14")
            if pd.notna(atr) and float(atr) > 0:
                pending = {"date": day, "atr": float(atr)}
    if pos is not None and len(df):
        last = df.iloc[-1]
        trades.append(_finish(symbol, instrument, pos, str(pd.Timestamp(df.index[-1]).date()),
                              float(last.Close), "END_OF_DATA", config))
    return trades

def metrics_mr(trades, key):
    vals = [float(t[key]) for t in sorted(trades, key=lambda x: (x["exit_date"], x["entry_date"]))]
    if not vals:
        return {"trades": 0, "win_rate_pct": 0, "avg_net_pct": 0, "median_net_pct": 0,
                "profit_factor": 0, "max_drawdown_pct": 0}
    wins, losses = [x for x in vals if x > 0], [x for x in vals if x < 0]
    equity = peak = 1.0
    dd = 0.0
    for value in vals:
        equity *= 1 + value / 100
        peak = max(peak, equity)
        dd = min(dd, (equity / peak - 1) * 100)
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    return {"trades": len(vals), "win_rate_pct": round(len(wins) / len(vals) * 100, 2),
            "avg_net_pct": round(sum(vals) / len(vals), 3),
            "median_net_pct": round(float(pd.Series(vals).median()), 3),
            "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else (999 if gross_profit else 0),
            "max_drawdown_pct": round(dd, 3),
            "best_trade_pct": round(max(vals), 3), "worst_trade_pct": round(min(vals), 3)}


def simulate_mr_variant(symbol, instrument, frame, config, variant="A"):
    """Run an isolated MR variant: A baseline, B lower-band recovery, C lower-band walk."""
    if variant not in {"A", "B", "C"}:
        raise ValueError("variant must be A, B or C")
    df = add_mr_indicators(frame, config)
    close = pd.to_numeric(df["Close"], errors="coerce")
    lower = df["MR_BB_LOWER"]
    base = df["MR_ENTRY_SIGNAL"].fillna(False)
    # C: at least 2/3 closes within 1.5% of the lower band and a strictly
    # falling lower band over the same three completed sessions.
    near_lower = ((close / lower - 1).abs() <= float(config.get("mr_walking_tolerance", 0.015))).fillna(False)
    lower_falling = (lower < lower.shift(1)) & (lower.shift(1) < lower.shift(2))
    c_signal = base & (near_lower.rolling(3, min_periods=3).sum() >= 2) & lower_falling
    trades, pos, pending_entry, setup = [], None, None, None
    stop_multiple = float(config.get("mr_atr_stop_multiple", 2.0))
    max_days = int(config.get("mr_max_holding_sessions", 10))

    for date, row in df.iterrows():
        day = str(pd.Timestamp(date).date())
        op, hi, lo, px = (float(row[x]) for x in ("Open", "High", "Low", "Close"))
        if not all(math.isfinite(x) and x > 0 for x in (op, hi, lo, px)):
            continue
        # Orders generated at a completed prior close are filled at today's open.
        if pending_entry is not None and pos is None:
            atr = float(pending_entry["atr"])
            pos = {"signal_date": pending_entry["date"], "entry_date": day,
                   "entry_price": op, "stop_price": op - stop_multiple * atr,
                   "holding_sessions": 0}
            pending_entry = None
            setup = None
        if pos is not None:
            pos["holding_sessions"] += 1
            if lo <= pos["stop_price"]:
                fill = op if op < pos["stop_price"] else pos["stop_price"]
                trades.append(_finish(symbol, instrument, pos, day, fill, "ATR14_X2_STOP", config))
                pos = None
                continue
            mid = row.get("MR_BB_MID")
            if pd.notna(mid) and px >= float(mid):
                trades.append(_finish(symbol, instrument, pos, day, px, "BB_MID_REVERSION", config))
                pos = None
                continue
            if pos["holding_sessions"] >= max_days:
                trades.append(_finish(symbol, instrument, pos, day, px, "MAX_HOLDING_SESSIONS", config))
                pos = None
                continue
            continue

        if pending_entry is not None:
            continue
        if variant == "B":
            if setup is not None:
                setup["sessions"] += 1
                if pd.notna(row.get("MR_BB_LOWER")) and px > float(row["MR_BB_LOWER"]):
                    setup["recoveries"] += 1
                if setup["recoveries"] >= 2:
                    pending_entry = {"date": setup["date"], "atr": setup["atr"]}
                    setup = None
                elif setup["sessions"] >= 3:
                    setup = None
            elif bool(base.loc[date]):
                atr = row.get("ATR14")
                if pd.notna(atr) and float(atr) > 0:
                    setup = {"date": day, "atr": float(atr), "sessions": 0, "recoveries": 0}
        else:
            signal = bool(base.loc[date]) if variant == "A" else bool(c_signal.loc[date])
            if signal:
                atr = row.get("ATR14")
                if pd.notna(atr) and float(atr) > 0:
                    pending_entry = {"date": day, "atr": float(atr)}

    if pos is not None and len(df):
        last = df.iloc[-1]
        trades.append(_finish(symbol, instrument, pos, str(pd.Timestamp(df.index[-1]).date()),
                              float(last.Close), "END_OF_DATA", config))
    for trade in trades:
        trade["strategy"] = "MEAN_REVERSION_" + variant
        trade["variant"] = variant
    return trades
