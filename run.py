#!/usr/bin/env python3
"""Daily data refresh and independent PAPER engine."""
import json, warnings
from pathlib import Path
import yfinance as yf
from paper_engine import load_state, save_state, process_frame, write_outputs

ROOT=Path(__file__).resolve().parent
warnings.filterwarnings("ignore")

def main():
    config=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
    universe=json.loads((ROOT/"data/instrument_universe.json").read_text(encoding="utf-8"))
    state=load_state()
    instruments=universe["instruments"]
    results=[]
    selected=[x for x in instruments if x.get("classification") in {
        "LEVA_LONG","LEVA_SHORT","MATERIE_PRIME_1X","MATERIE_PRIME_LEVA","MATERIE_PRIME_SHORT"
    }]
    print(f"SNIPERCHATGPT PAPER ONLY | selected={len(selected)}")
    for inst in selected:
        symbol=inst.get("yahoo") or inst.get("id")
        try:
            raw=yf.download(symbol,period=config["history_period"],interval="1d",
                            auto_adjust=False,actions=True,progress=False,threads=False)
            if raw is None or raw.empty:
                results.append({"symbol":symbol,"status":"SKIPPED","reason":"dati assenti"})
                continue
            if getattr(raw.columns,"nlevels",1)>1:
                raw.columns=raw.columns.get_level_values(0)
            raw=raw[~raw.index.duplicated(keep="last")].dropna(subset=["Open","High","Low","Close"])
            result=process_frame(state,symbol,inst,raw,config)
            results.append(result)
        except Exception as exc:
            results.append({"symbol":symbol,"status":"ERROR","reason":str(exc)[:240]})
    save_state(state)
    summary=write_outputs(state)
    counts={}
    for r in results: counts[r["status"]]=counts.get(r["status"],0)+1
    print(json.dumps({"universe":len(selected),"counts":counts,"paper_summary":summary,
                      "skipped_or_errors":[r for r in results if r["status"]!="OK"][:100]},
                     ensure_ascii=False,indent=2))

if __name__=="__main__": main()
