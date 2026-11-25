#!/usr/bin/env python3
"""Fetch USA reference closes for the independent informational radar. PAPER only."""
import json, os, sys
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import yfinance as yf

ROOT=Path(__file__).resolve().parent
MAPPING=ROOT/"data/us_underlying_mapping.json"
OUT=ROOT/"reports/us_radar.json"

def main():
    local_now=datetime.now(ZoneInfo("Europe/Rome"))
    if os.environ.get("GITHUB_EVENT_NAME")=="schedule" and local_now.hour not in (7,23):
        print("Skip: outside Rome 07:xx or 23:xx scheduled windows (DST guard).")
        return
    mapping=json.loads(MAPPING.read_text(encoding="utf-8"))
    refs=set()
    for row in mapping["records"]:
        if row["mapping_status"] not in ("candidate","proxy_or_unverified"):
            continue
        for ref in (row.get("us_reference") or "").split(";"):
            ref=ref.strip()
            if ref and ref.lower() not in ("nessuno","nessuno","alum","cn h= x") and " " not in ref:
                refs.add(ref)
    quotes={}
    symbols=sorted(refs)
    if symbols:
        raw=yf.download(tickers=symbols,period="5d",interval="1d",auto_adjust=True,
                        progress=False,threads=False,group_by="ticker",timeout=30)
        for symbol in symbols:
            try:
                frame=raw[symbol] if getattr(raw.columns,"nlevels",1)>1 and symbol in raw.columns.get_level_values(0) else raw
                frame=frame.dropna(subset=["Close"])
                if len(frame)<1: raise ValueError("nessuna chiusura disponibile")
                last=frame.iloc[-1]
                prev=frame.iloc[-2] if len(frame)>1 else None
                close=float(last["Close"])
                pct=((close/float(prev["Close"]))-1)*100 if prev is not None else None
                quotes[symbol]={"date":str(frame.index[-1].date()),"close":round(close,6),
                                "change_pct":round(pct,3) if pct is not None else None,"status":"OK"}
            except Exception as exc:
                quotes[symbol]={"status":"UNAVAILABLE","reason":str(exc)[:140]}
    results=[]
    for row in mapping["records"]:
        refs=[x.strip() for x in (row.get("us_reference") or "").split(";") if x.strip()]
        selected=[x for x in refs if x in quotes]
        q=[{"ticker":x,**quotes[x]} for x in selected]
        if not refs or row["mapping_status"] in ("manual_review_required","no_direct_equivalent"):
            status="NON_MAPPATO"
        elif not q or all(x["status"]!="OK" for x in q):
            status="DATO_NON_DISPONIBILE"
        elif row["confidence"]=="bassa" or row["mapping_status"]=="proxy_or_unverified":
            status="PROXY_DA_VERIFICARE"
        else:
            status="RIFERIMENTO_DISPONIBILE"
        results.append({"etp":row["etp"],"name":row["name"],"reference":row.get("us_reference"),
                        "confidence":row["confidence"],"mapping_status":row["mapping_status"],
                        "radar_status":status,"quotes":q})
    out={"schema_version":"1.0","generated_utc":datetime.now(timezone.utc).isoformat(),
         "generated_rome":datetime.now(ZoneInfo("Europe/Rome")).isoformat(),
         "paper_only":True,"interpretation":"Il radar mostra il movimento del riferimento USA; non modifica né genera segnali TF/MR.",
         "quotes_count":len(quotes),"records_count":len(results),"records":results}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"USA Radar: {len(results)} ETP; {len(quotes)} riferimenti interrogati; {OUT}")

if __name__=="__main__": main()
