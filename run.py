#!/usr/bin/env python3
"""Batched daily data refresh and independent PAPER engine."""
import json, warnings
from pathlib import Path
import yfinance as yf
from paper_engine import load_state, save_state, process_frame, write_outputs

ROOT=Path(__file__).resolve().parent
warnings.filterwarnings("ignore")

def split_symbol_frame(raw, symbol):
    if raw is None or raw.empty:
        return None
    if getattr(raw.columns,"nlevels",1)>1:
        if symbol in raw.columns.get_level_values(0):
            frame=raw[symbol].copy()
        elif symbol in raw.columns.get_level_values(1):
            frame=raw.xs(symbol,axis=1,level=1).copy()
        else:
            return None
    else:
        frame=raw.copy()
    required={"Open","High","Low","Close"}
    if not required.issubset(frame.columns):
        return None
    return frame

def main():
    config=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
    universe=json.loads((ROOT/"data/instrument_universe.json").read_text(encoding="utf-8"))
    state=load_state()
    selected=[x for x in universe["instruments"] if x.get("classification") in {
        "LEVA_LONG","LEVA_SHORT","MATERIE_PRIME_1X","MATERIE_PRIME_LEVA","MATERIE_PRIME_SHORT"
    }]
    # Batch downloads reduce provider calls and rate-limit exposure.
    batch_size=20
    results=[]
    print(f"SNIPERCHATGPT PAPER ONLY | selected={len(selected)} | batches={(len(selected)+batch_size-1)//batch_size}")
    for start in range(0,len(selected),batch_size):
        batch=selected[start:start+batch_size]
        symbols=[x.get("yahoo") or x.get("id") for x in batch]
        try:
            raw=yf.download(tickers=symbols,period=config["history_period"],interval="1d",
                            auto_adjust=False,actions=True,progress=False,threads=False,
                            group_by="ticker",timeout=25)
        except Exception as exc:
            for inst,symbol in zip(batch,symbols):
                results.append({"symbol":symbol,"status":"ERROR","reason":str(exc)[:200]})
            continue
        for inst,symbol in zip(batch,symbols):
            try:
                frame=split_symbol_frame(raw,symbol)
                if frame is None or frame.empty:
                    results.append({"symbol":symbol,"status":"SKIPPED","reason":"dati assenti o mapping Yahoo non disponibile"})
                    continue
                frame=frame[~frame.index.duplicated(keep="last")].dropna(subset=["Open","High","Low","Close"])
                result=process_frame(state,symbol,inst,frame,config)
                results.append(result)
            except Exception as exc:
                results.append({"symbol":symbol,"status":"ERROR","reason":str(exc)[:240]})
    save_state(state)
    summary=write_outputs(state)
    counts={}
    for result in results:
        counts[result["status"]]=counts.get(result["status"],0)+1
    print(json.dumps({"universe":len(selected),"counts":counts,"paper_summary":summary,
                      "skipped_or_errors":[r for r in results if r["status"]!="OK"][:150]},
                     ensure_ascii=False,indent=2))

if __name__=="__main__": main()
