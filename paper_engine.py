"""Stateful PAPER-only engine. No broker connectivity and no real orders."""
from __future__ import annotations
import json, math
from pathlib import Path
import pandas as pd
from strategy import add_indicators, entry_reason

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "data" / "paper_state.json"
TRADES_PATH = ROOT / "data" / "paper_trades.csv"
SUMMARY_PATH = ROOT / "data" / "paper_summary.json"

def blank_state():
    return {"schema_version":1,"paper_only":True,"last_processed":{},"positions":{},"pending_entries":{},"pending_exits":{},"trades":[],"signals":[]}

def load_state(path=STATE_PATH):
    if not path.exists(): return blank_state()
    state=json.loads(path.read_text(encoding="utf-8"))
    if state.get("paper_only") is not True: raise ValueError("Refusing non-PAPER state")
    return state

def save_state(state, path=STATE_PATH):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(state,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf-8")

def _close_trade(state, symbol, pos, date, price, reason):
    entry=float(pos["entry_price"]); exit_price=float(price)
    gross=(exit_price/entry-1)*100
    state["trades"].append({
        "symbol":symbol,"name":pos.get("name"),"category":pos["category"],
        "signal_date":pos["signal_date"],"entry_date":pos["entry_date"],
        "entry_price":round(entry,8),"exit_date":str(date),"exit_price":round(exit_price,8),
        "holding_sessions":int(pos["holding_sessions"]),"exit_reason":reason,
        "gross_return_pct":round(gross,4),
        "net_return_pct_by_cost_bps":{str(b):round(gross-b/100,4) for b in (20,30,50)}
    })
    state["positions"].pop(symbol,None)

def process_bar(state, symbol, instrument, date, row, config):
    """Process one completed daily candle, using only this and past bars."""
    date=str(pd.Timestamp(date).date())
    category=instrument["classification"]
    # A close-generated exit is executed at the next available session open.
    if symbol in state["pending_exits"] and symbol in state["positions"]:
        pos=state["positions"][symbol]
        _close_trade(state,symbol,pos,date,float(row.Open),state["pending_exits"].pop(symbol))
    # A close-generated entry is executed at the next available session open.
    if symbol in state["pending_entries"] and symbol not in state["positions"]:
        pending=state["pending_entries"].pop(symbol)
        op=float(row.Open)
        if math.isfinite(op) and op>0:
            state["positions"][symbol]={
                "name":instrument.get("name"),"category":category,
                "signal_date":pending["signal_date"],"entry_date":date,
                "entry_price":op,"initial_atr":pending["atr"],
                "stop_price":op-float(config["atr_stop_multiple"])*pending["atr"],
                "holding_sessions":0,"walking_false_streak":0
            }
    pos=state["positions"].get(symbol)
    if pos:
        pos["holding_sessions"]+=1
        low=float(row.Low); op=float(row.Open); close=float(row.Close)
        stop=float(pos["stop_price"])
        if low<=stop:
            fill=op if op<stop else stop
            _close_trade(state,symbol,pos,date,fill,"ATR14_X2_STOP")
            return
        pos["walking_false_streak"] = 0 if bool(row.WALKING) else pos["walking_false_streak"]+1
        if pos["holding_sessions"]>=int(config["max_holding_sessions"]):
            _close_trade(state,symbol,pos,date,close,"MAX_10_SESSIONS")
            return
        if pos["walking_false_streak"]>=2:
            state["pending_exits"][symbol]="WALKING_FALSE_2_CLOSES"
            return
    if (symbol not in state["positions"] and symbol not in state["pending_entries"]
            and symbol not in state["pending_exits"] and bool(row.ENTRY_SIGNAL)):
        state["pending_entries"][symbol]={"signal_date":date,"atr":float(row.ATR14)}
        state["signals"].append({
            "symbol":symbol,"name":instrument.get("name"),"category":category,
            "signal_date":date,"close":round(float(row.Close),8),
            "donchian20":round(float(row.DONCHIAN20_UPPER),8),
            "walking":bool(row.WALKING),"atr14":round(float(row.ATR14),8),
            "stop_reference_close_estimate":round(float(row.Close)-float(config["atr_stop_multiple"])*float(row.ATR14),8),
            "action":"BUY_PAPER_NEXT_OPEN","reason":entry_reason(row)
        })

def process_frame(state, symbol, instrument, frame, config):
    if len(frame)<int(config["minimum_bars"]):
        return {"symbol":symbol,"status":"SKIPPED","reason":f"storico insufficiente: {len(frame)} barre"}
    df=add_indicators(frame,config)
    last=state["last_processed"].get(symbol)
    if last:
        rows=df.loc[df.index.map(lambda x:str(pd.Timestamp(x).date())>last)]
    else:
        # On first observation, historical bars initialize indicators only.
        rows=df.tail(1)
    processed=0
    for date,row in rows.iterrows():
        if not all(math.isfinite(float(row[c])) for c in ("Open","High","Low","Close")):
            continue
        process_bar(state,symbol,instrument,date,row,config)
        state["last_processed"][symbol]=str(pd.Timestamp(date).date())
        processed+=1
    return {"symbol":symbol,"status":"OK","bars_processed":processed,"latest_date":str(pd.Timestamp(df.index[-1]).date())}

def write_outputs(state):
    TRADES_PATH.parent.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(state["trades"]).to_csv(TRADES_PATH,index=False)
    summary={
        "paper_only":True,"positions_open":len(state["positions"]),
        "pending_entries":len(state["pending_entries"]),"pending_exits":len(state["pending_exits"]),
        "closed_trades":len(state["trades"]),"signals_total":len(state["signals"]),
        "latest_signals":state["signals"][-50:],"open_positions":state["positions"],
        "updated_at_utc":pd.Timestamp.now(tz="UTC").isoformat()
    }
    SUMMARY_PATH.write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return summary
