#!/usr/bin/env python3
"""Historical, instrument-level backtest using the same v1 entry/exit rules."""
import json, math, warnings
from pathlib import Path
import pandas as pd
import yfinance as yf
from strategy import add_indicators
ROOT=Path(__file__).resolve().parent
OUT=ROOT/"reports"
warnings.filterwarnings("ignore")

def finish(symbol, instrument, pos, date, price, reason, config):
    gross=(float(price)/pos["entry_price"]-1)*100
    row={"symbol":symbol,"name":instrument.get("name",symbol),"category":instrument["classification"],
         "signal_date":pos["signal_date"],"entry_date":pos["entry_date"],"entry_price":round(pos["entry_price"],8),
         "exit_date":date,"exit_price":round(float(price),8),"holding_sessions":pos["holding_sessions"],
         "exit_reason":reason,"gross_return_pct":round(gross,5)}
    for bps in config["costs_bps_round_trip"]: row[f"net_{bps}bps_pct"]=round(gross-float(bps)/100,5)
    return row

def simulate(symbol, instrument, frame, config):
    df=add_indicators(frame,config); trades=[]; pos=None; pending_entry=None; pending_exit=None
    for date,row in df.iterrows():
        day=str(pd.Timestamp(date).date())
        op,hi,lo,close=(float(row[x]) for x in ("Open","High","Low","Close"))
        if not all(math.isfinite(x) and x>0 for x in (op,hi,lo,close)): continue
        if pending_exit and pos:
            trades.append(finish(symbol,instrument,pos,day,op,pending_exit,config)); pos=None; pending_exit=None
        if pending_entry and pos is None:
            atr=float(pending_entry["atr"])
            pos={"signal_date":pending_entry["date"],"entry_date":day,"entry_price":op,"atr14":atr,
                 "stop_price":op-float(config["atr_stop_multiple"])*atr,"holding_sessions":0,"walking_false_streak":0}
            pending_entry=None
        if pos:
            pos["holding_sessions"]+=1
            if lo<=pos["stop_price"]:
                fill=op if op<pos["stop_price"] else pos["stop_price"]
                trades.append(finish(symbol,instrument,pos,day,fill,"ATR14_X2_STOP",config)); pos=None; continue
            pos["walking_false_streak"]=0 if bool(row.WALKING) else pos["walking_false_streak"]+1
            if pos["holding_sessions"]>=int(config["max_holding_sessions"]):
                trades.append(finish(symbol,instrument,pos,day,close,"MAX_10_SESSIONS",config)); pos=None; continue
            if pos["walking_false_streak"]>=2:
                pending_exit="WALKING_FALSE_2_CLOSES"; continue
        if pos is None and pending_entry is None and pending_exit is None and bool(row.ENTRY_SIGNAL):
            pending_entry={"date":day,"atr":float(row.ATR14)}
    if pos:
        trades.append(finish(symbol,instrument,pos,str(pd.Timestamp(df.index[-1]).date()),float(df.iloc[-1].Close),"END_OF_DATA",config))
    return trades

def metrics(trades,key):
    if not trades: return {"trades":0,"win_rate_pct":0,"avg_net_pct":0,"median_net_pct":0,"profit_factor":0,"max_drawdown_pct":0}
    vals=[float(t[key]) for t in trades]; wins=[x for x in vals if x>0]; losses=[x for x in vals if x<0]
    equity=peak=1.0; dd=0.0
    for x in vals:
        equity*=1+x/100; peak=max(peak,equity); dd=min(dd,(equity/peak-1)*100)
    gp=sum(wins); gl=abs(sum(losses))
    return {"trades":len(vals),"win_rate_pct":round(len(wins)/len(vals)*100,2),
      "avg_net_pct":round(sum(vals)/len(vals),3),"median_net_pct":round(float(pd.Series(vals).median()),3),
      "profit_factor":round(gp/gl,3) if gl else (999 if gp else 0),"max_drawdown_pct":round(dd,3),
      "best_trade_pct":round(max(vals),3),"worst_trade_pct":round(min(vals),3)}

def main():
    config=json.loads((ROOT/"config.json").read_text())
    universe=json.loads((ROOT/"data/instrument_universe.json").read_text())["instruments"]
    selected=[x for x in universe if x.get("classification") in {"LEVA_LONG","LEVA_SHORT","MATERIE_PRIME_1X","MATERIE_PRIME_LEVA","MATERIE_PRIME_SHORT"}]
    all_trades=[]; scan=[]; batch_size=20
    for start in range(0,len(selected),batch_size):
        batch=selected[start:start+batch_size]; tickers=[x.get("yahoo") or x.get("id") for x in batch]
        try:
            raw=yf.download(tickers=tickers,period=config["history_period"],interval="1d",auto_adjust=True,
                            progress=False,threads=False,group_by="ticker",timeout=30)
        except Exception as e:
            scan.extend({"symbol":s,"category":i["classification"],"status":"ERROR","reason":str(e)[:180]} for i,s in zip(batch,tickers)); continue
        for inst,symbol in zip(batch,tickers):
            try:
                if getattr(raw.columns,"nlevels",1)>1:
                    if symbol in raw.columns.get_level_values(0): frame=raw[symbol].copy()
                    elif symbol in raw.columns.get_level_values(1): frame=raw.xs(symbol,axis=1,level=1).copy()
                    else: frame=pd.DataFrame()
                else: frame=raw.copy()
                if frame.empty or not {"Open","High","Low","Close"}.issubset(frame.columns):
                    scan.append({"symbol":symbol,"category":inst["classification"],"status":"SKIPPED","reason":"OHLC non disponibili"}); continue
                frame=frame[~frame.index.duplicated(keep="last")].dropna(subset=["Open","High","Low","Close"])
                if len(frame)<int(config["minimum_bars"]):
                    scan.append({"symbol":symbol,"category":inst["classification"],"status":"SKIPPED","reason":f"solo {len(frame)} barre OHLC"}); continue
                trades=simulate(symbol,inst,frame,config); all_trades.extend(trades)
                scan.append({"symbol":symbol,"category":inst["classification"],"status":"OK","bars":len(frame),
                             "first_date":str(pd.Timestamp(frame.index[0]).date()),"last_date":str(pd.Timestamp(frame.index[-1]).date()),"trades":len(trades)})
            except Exception as e: scan.append({"symbol":symbol,"category":inst["classification"],"status":"ERROR","reason":str(e)[:220]})
    OUT.mkdir(exist_ok=True)
    pd.DataFrame(all_trades).to_csv(OUT/"backtest_trades.csv",index=False)
    pd.DataFrame(scan).to_csv(OUT/"backtest_data_audit.csv",index=False)
    keys=[f"net_{b}bps_pct" for b in config["costs_bps_round_trip"]]; families=[]
    for cat in sorted({x["classification"] for x in selected}):
        group=[t for t in all_trades if t["category"]==cat]; source=[s for s in scan if s["category"]==cat]
        rec={"category":cat,"universe":sum(x["classification"]==cat for x in selected),
             "data_ok":sum(x["status"]=="OK" for x in source),"skipped":sum(x["status"]=="SKIPPED" for x in source),
             "errors":sum(x["status"]=="ERROR" for x in source)}
        for key in keys:
            for k,v in metrics(group,key).items(): rec[f"{key}_{k}"]=v
        families.append(rec)
    instruments=[]
    for item in scan:
        group=[t for t in all_trades if t["symbol"]==item["symbol"]]; rec=dict(item)
        for key in keys:
            for k,v in metrics(group,key).items(): rec[f"{key}_{k}"]=v
        instruments.append(rec)
    summary={"generated_utc":pd.Timestamp.now(tz="UTC").isoformat(),
      "method":"Donchian20 breakout + Walking 2/3; entry next open; ATR14x2 stop; exit after 2 Walking-false closes next open; max 10 sessions at close; adjusted OHLC",
      "history_period":config["history_period"],"costs_bps_round_trip":config["costs_bps_round_trip"],
      "paper_only":True,"not_a_live_signal":True,"universe_total":len(selected),
      "data_ok":sum(x["status"]=="OK" for x in scan),"skipped":sum(x["status"]=="SKIPPED" for x in scan),
      "errors":sum(x["status"]=="ERROR" for x in scan),"trades_total":len(all_trades),
      "families":families,"instruments":instruments}
    (OUT/"backtest_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({k:summary[k] for k in ("universe_total","data_ok","skipped","errors","trades_total","families")},indent=2,ensure_ascii=False))
if __name__=="__main__": main()
