#!/usr/bin/env python3
"""Historical, instrument-level backtest using the same v1 entry/exit rules."""
import json, math, warnings
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import pandas as pd
import yfinance as yf
from strategy import add_indicators
from mean_reversion import add_mr_indicators, simulate_mr_variant, metrics_mr
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
    trades=sorted(trades,key=lambda x:(x["exit_date"],x["entry_date"]))

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
    all_trades=[]; mr_all_trades=[]; mr_variant_trades={"A":[],"B":[],"C":[],"D":[]}; scan=[]; market_data={}; mr_diag={"valid_bars":0,"below_lower":0,"rsi2_le_10":0,"both_conditions":0,"entry_signals":0}; batch_size=20
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
                now=datetime.now(ZoneInfo("Europe/Rome"))
                if now.hour<18:
                    frame=frame[[pd.Timestamp(d).date()<now.date() for d in frame.index]]
                if len(frame)<int(config["minimum_bars"]):
                    scan.append({"symbol":symbol,"category":inst["classification"],"status":"SKIPPED","reason":f"solo {len(frame)} barre OHLC"}); continue
                daily_returns=frame["Close"].pct_change().dropna()
                max_jump=float(daily_returns.max()*100) if not daily_returns.empty else 0.0
                min_jump=float(daily_returns.min()*100) if not daily_returns.empty else 0.0
                if max_jump>300 or min_jump < -80:
                    scan.append({"symbol":symbol,"category":inst["classification"],"status":"SUSPICIOUS",
                                 "reason":"discontinuità prezzo: variazione giornaliera oltre soglia",
                                 "max_daily_change_pct":round(max_jump,2),"min_daily_change_pct":round(min_jump,2),
                                 "bars":len(frame)})
                    continue
                indicated=add_indicators(frame,config)
                mr_indicated=add_mr_indicators(frame,config)
                below=mr_indicated["Close"].le(mr_indicated["MR_BB_LOWER"])
                oversold=mr_indicated["MR_RSI2"].le(float(config.get("mr_rsi_entry",10)))
                mr_diag["valid_bars"]+=len(frame)
                mr_diag["below_lower"]+=int(below.sum())
                mr_diag["rsi2_le_10"]+=int(oversold.sum())
                mr_diag["both_conditions"]+=int((below & oversold).sum())
                mr_diag["entry_signals"]+=int(mr_indicated["MR_ENTRY_SIGNAL"].sum())
                cols=["Open","High","Low","Close","Volume","DONCHIAN20_UPPER","BB_UPPER","BB_MID","ATR14","WALKING","ENTRY_SIGNAL"]
                export=indicated.reindex(columns=cols).copy()
                export["MR_BB_LOWER"]=mr_indicated["MR_BB_LOWER"]
                export["MR_RSI2"]=mr_indicated["MR_RSI2"]
                export["MR_ENTRY_SIGNAL"]=mr_indicated["MR_ENTRY_SIGNAL"]
                records=[]
                for dt,values in export.iterrows():
                    rec={"date":pd.Timestamp(dt).strftime("%Y-%m-%d")}
                    for col in export.columns:
                        value=values.get(col)
                        if pd.isna(value): rec[col.lower()]=None
                        elif col in ("WALKING","ENTRY_SIGNAL","MR_ENTRY_SIGNAL"): rec[col.lower()]=bool(value)
                        elif col=="Volume": rec["volume"]=int(value)
                        else: rec[col.lower()]=round(float(value),6)
                    records.append(rec)
                market_data[symbol]={"name":inst.get("name",symbol),"category":inst["classification"],"bars":records}
                trades=simulate(symbol,inst,frame,config); all_trades.extend(trades)
                current_mr={}
                for variant in ("A","B","C","D"):
                    current_mr[variant]=simulate_mr_variant(symbol,inst,frame,config,variant)
                    mr_variant_trades[variant].extend(current_mr[variant])
                mr_all_trades.extend(current_mr["A"])
                scan.append({"symbol":symbol,"category":inst["classification"],"status":"OK","bars":len(frame),
                             "first_date":str(pd.Timestamp(frame.index[0]).date()),"last_date":str(pd.Timestamp(frame.index[-1]).date()),
                             "max_daily_change_pct":round(max_jump,2),"min_daily_change_pct":round(min_jump,2),"trades":len(trades)})
            except Exception as e: scan.append({"symbol":symbol,"category":inst["classification"],"status":"ERROR","reason":str(e)[:220]})
    OUT.mkdir(exist_ok=True)
    (OUT/"market_data.json").write_text(json.dumps({"generated_utc":pd.Timestamp.now(tz="UTC").isoformat(),"source":"Yahoo Finance auto_adjust OHLCV; same daily bars used by backtest","instruments":market_data},separators=(",",":"),ensure_ascii=False)+"
",encoding="utf-8")
    pd.DataFrame(all_trades).to_csv(OUT/"backtest_trades.csv",index=False)
    pd.DataFrame(mr_all_trades).to_csv(OUT/"mr_backtest_trades.csv",index=False)
    for variant in ("B","C","D"):
        pd.DataFrame(mr_variant_trades[variant]).to_csv(OUT/f"mr_backtest_trades_{variant.lower()}.csv",index=False)
    pd.DataFrame(scan).to_csv(OUT/"backtest_data_audit.csv",index=False)
    def mr_instrument_drawdowns(trades,key):
        values=[metrics_mr([t for t in trades if t["symbol"]==sym],key)["max_drawdown_pct"]
                for sym in sorted({t["symbol"] for t in trades})]
        return {
            "avg_instrument_drawdown_pct":round(sum(values)/len(values),3) if values else 0,
            "worst_instrument_drawdown_pct":round(min(values),3) if values else 0
        }
    mr_costs={}
    for bps in config["costs_bps_round_trip"]:
        key="net_"+str(bps)+"bps_pct"
        m=metrics_mr(mr_all_trades,key)
        m.pop("max_drawdown_pct",None)
        m.update(mr_instrument_drawdowns(mr_all_trades,key))
        mr_costs[str(bps)]=m
    mr_families=[]
    for cat in sorted({x["classification"] for x in selected}):
        group=[t for t in mr_all_trades if t["category"]==cat]
        rec={"category":cat}
        for bps in config["costs_bps_round_trip"]:
            key="net_"+str(bps)+"bps_pct"
            m=metrics_mr(group,key)
            m.pop("max_drawdown_pct",None)
            m.update(mr_instrument_drawdowns(group,key))
            for k,v in m.items(): rec[key+"_"+k]=v
        mr_families.append(rec)
    def summarize_mr_variant(trades):
        costs={}
        for bps in config["costs_bps_round_trip"]:
            key="net_"+str(bps)+"bps_pct"
            m=metrics_mr(trades,key); m.pop("max_drawdown_pct",None)
            m.update(mr_instrument_drawdowns(trades,key)); costs[str(bps)]=m
        families=[]
        for cat in sorted({x["classification"] for x in selected}):
            group=[t for t in trades if t["category"]==cat]; rec={"category":cat}
            for bps in config["costs_bps_round_trip"]:
                key="net_"+str(bps)+"bps_pct"; m=metrics_mr(group,key); m.pop("max_drawdown_pct",None)
                m.update(mr_instrument_drawdowns(group,key))
                for k,v in m.items(): rec[key+"_"+k]=v
            families.append(rec)
        return {"trades_total":len(trades),"costs":costs,"families":families}
    mr_variants={v:summarize_mr_variant(mr_variant_trades[v]) for v in ("A","B","C","D")}
    mr_summary={"strategy":"MEAN_REVERSION","rules":{
        "setup":"Close sotto Bollinger inferiore (20,2) e RSI(2) <= 10 sulla stessa seduta",
        "entry":"Segnale sulla chiusura; ingresso all'open della seduta successiva",
        "stop":"2 x ATR(14) dal prezzo di ingresso, ATR calcolato alla data del segnale",
        "exit":"Chiusura al raggiungimento/superamento della Bollinger centrale; stop ATR; massimo 10 sedute",
        "independent_from_trend_following":True,
        "A":"Baseline: entry next open after oversold signal",
        "B":"After oversold setup, enter next open once at least 2 of the next 3 closes are above the lower Bollinger band; discard if not confirmed within 3 sessions",
        "C":"At oversold signal, require at least 2 of the last 3 closes within 1.5% of the lower band and lower band falling on each of the last 2 transitions",
        "D":"40% initial entry on A signal; add 30% on each of two fresh post-entry lower-band Walking confirmations (2 of 3 closes within 1.5%, lower band falling); fixed initial stop, common exit; unused allocation stays in cash"},
        "trades_total":len(mr_all_trades),"diagnostics":mr_diag,"costs":mr_costs,"families":mr_families,"variants":mr_variants,"paper_only":True}
    (OUT/"mr_backtest_summary.json").write_text(json.dumps(mr_summary,indent=2,ensure_ascii=False)+"
")
    keys=[f"net_{b}bps_pct" for b in config["costs_bps_round_trip"]]; families=[]
    for cat in sorted({x["classification"] for x in selected}):
        group=[t for t in all_trades if t["category"]==cat]; source=[s for s in scan if s["category"]==cat]
        rec={"category":cat,"universe":sum(x["classification"]==cat for x in selected),
             "data_ok":sum(x["status"]=="OK" for x in source),"skipped":sum(x["status"] in ("SKIPPED","SUSPICIOUS") for x in source),
             "suspicious":sum(x["status"]=="SUSPICIOUS" for x in source),
             "errors":sum(x["status"]=="ERROR" for x in source)}
        for key in keys:
            m=metrics(group,key)
            for k,v in m.items():
                if k!="max_drawdown_pct": rec[f"{key}_{k}"]=v
            ticker_dd=[metrics([t for t in group if t["symbol"]==sym],key)["max_drawdown_pct"]
                       for sym in sorted({t["symbol"] for t in group})]
            rec[f"{key}_avg_instrument_drawdown_pct"]=round(sum(ticker_dd)/len(ticker_dd),3) if ticker_dd else 0
            rec[f"{key}_worst_instrument_drawdown_pct"]=round(min(ticker_dd),3) if ticker_dd else 0
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
      "data_ok":sum(x["status"]=="OK" for x in scan),"skipped":sum(x["status"] in ("SKIPPED","SUSPICIOUS") for x in scan),
      "suspicious":sum(x["status"]=="SUSPICIOUS" for x in scan),
      "price_jump_filter":{"max_daily_rise_pct":300,"max_daily_drop_pct":-80},
      "errors":sum(x["status"]=="ERROR" for x in scan),"trades_total":len(all_trades),
      "families":families,"instruments":instruments,
      "mean_reversion":{"summary_file":"mr_backtest_summary.json","trades_file":"mr_backtest_trades.csv",
                        "trades_total":len(mr_all_trades),"independent_engine":True}}
    (OUT/"backtest_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"
")
    print(json.dumps({k:summary[k] for k in ("universe_total","data_ok","skipped","errors","trades_total","families")},indent=2,ensure_ascii=False))
if __name__=="__main__": main()
