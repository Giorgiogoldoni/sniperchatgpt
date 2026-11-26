#!/usr/bin/env python3
"""Build weekly Sniper RRG data from the same adjusted histories as the backtest."""
import json, warnings
from pathlib import Path
import pandas as pd
import yfinance as yf
warnings.filterwarnings("ignore")
ROOT=Path(__file__).resolve().parent
OUT=ROOT/"reports"
BENCH={"SPY":"S&P 500","QQQ":"Nasdaq 100","DBC":"Broad commodities","GLD":"Gold"}
def weekly(series):
    s=series.dropna().copy()
    s.index=pd.to_datetime(s.index)
    return s.resample("W-FRI").last().dropna()
def zscore(values,window=52):
    out=[]
    for i,v in enumerate(values):
        hist=[x for x in values[max(0,i-window+1):i+1] if x is not None]
        if len(hist)<12 or v is None: out.append(None); continue
        mean=sum(hist)/len(hist)
        sd=(sum((x-mean)**2 for x in hist)/len(hist))**.5
        out.append(0 if sd==0 else max(-4,min(4,(v-mean)/sd)))
    return out
def make_points(prices,bench):
    p=pd.Series(prices,dtype=float); b=pd.Series(bench,dtype=float)
    df=pd.concat([p.rename("p"),b.rename("b")],axis=1).dropna()
    if len(df)<30:return []
    rel=(df.p/df.b).apply(lambda x:100*__import__("math").log(x))
    rs=rel-rel.shift(12)
    mom=rs-rs.shift(4)
    xv=zscore(rs.tolist(),52); yv=zscore(mom.tolist(),52)
    return [{"date":d.strftime("%Y-%m-%d"),"x":round(100+v*5,3),"y":round(100+(yv[i] or 0)*5,3)}
            for i,(d,v) in enumerate(zip(df.index,xv)) if v is not None and yv[i] is not None]
def main():
    OUT.mkdir(exist_ok=True)
    raw=json.loads((OUT/"market_data.json").read_text())
    uni=json.loads((ROOT/"data/instrument_universe.json").read_text())["instruments"]
    meta={x.get("yahoo") or x.get("id"):x for x in uni}
    bench_series={}
    for sym in BENCH:
        try:
            d=yf.download(sym,period="2y",interval="1d",auto_adjust=True,progress=False,threads=False)
            if not d.empty:
                c=d["Close"]
                if isinstance(c,pd.DataFrame):c=c.iloc[:,0]
                bench_series[sym]={x.strftime("%Y-%m-%d"):float(y) for x,y in weekly(c).items()}
        except Exception as e: print("Benchmark",sym,"failed:",str(e)[:160])
    weekly_b={k:pd.Series(v,dtype=float) for k,v in bench_series.items()}
    inst={}
    for symbol,item in raw.get("instruments",{}).items():
        m=meta.get(symbol,{})
        bars=item.get("bars",[])
        s=pd.Series({x["date"]:x.get("close") for x in bars if x.get("close")},dtype=float)
        if len(s)<30:continue
        s.index=pd.to_datetime(s.index)
        w=weekly(s)
        if len(w)<30:continue
        p={d.strftime("%Y-%m-%d"):float(v) for d,v in w.items()}
        cat=m.get("classification",item.get("category",""))
        commodity=cat.startswith("MATERIE_PRIME")
        lev=float(m.get("leverage") or 1)
        short=bool(m.get("short")) or cat in ("LEVA_SHORT","MATERIE_PRIME_SHORT")
        inst[symbol]={"ticker":m.get("ticker") or symbol,"name":m.get("name") or item.get("name") or symbol,
          "category":cat,"leverage":lev,"commodity":commodity,"short":short,"prices":p,"rrg":{}}
        for bench,bs in weekly_b.items():
            inst[symbol]["rrg"][bench]=make_points(w,bs)
    payload={"generated_utc":pd.Timestamp.now(tz="UTC").isoformat(),"source":"Yahoo adjusted weekly closes; RRG approximation, not proprietary JdK",
      "benchmarks":BENCH,"benchmark_prices":bench_series,"instruments":inst,
      "method":{"RS":"12-week relative log return","RS-Momentum":"4-week change in RS","normalization":"rolling 52-week z-score, clipped +/-4, centered 100, scale 5"}}
    (OUT/"sniper_rrg.json").write_text(json.dumps(payload,separators=(",",":"),ensure_ascii=False)+"\n",encoding="utf-8")
    print("RRG generated",len(inst),"instruments; benchmarks",list(bench_series))
if __name__=="__main__":main()
