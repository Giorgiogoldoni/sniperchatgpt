#!/usr/bin/env python3
"""Build a weekly Sniper RRG data set from fresh adjusted Yahoo closes."""
import json, math, warnings
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
def extract_close(raw,symbol):
    if raw is None or raw.empty:return None
    try:
        if getattr(raw.columns,"nlevels",1)>1:
            if symbol in raw.columns.get_level_values(0): frame=raw[symbol]
            elif symbol in raw.columns.get_level_values(1): frame=raw.xs(symbol,axis=1,level=1)
            else:return None
        else:frame=raw
        c=frame["Close"]
        if isinstance(c,pd.DataFrame):c=c.iloc[:,0]
        return c.dropna()
    except Exception:return None
def zscore(values,window=52):
    out=[]
    for i,v in enumerate(values):
        hist=[float(x) for x in values[max(0,i-window+1):i+1] if x is not None and math.isfinite(float(x))]
        if len(hist)<12 or v is None or not math.isfinite(float(v)):out.append(None);continue
        mean=sum(hist)/len(hist);sd=(sum((x-mean)**2 for x in hist)/len(hist))**.5
        out.append(0 if sd==0 else max(-4,min(4,(float(v)-mean)/sd)))
    return out
def make_points(prices,bench):
    p=pd.Series(prices,dtype=float);b=pd.Series(bench,dtype=float)
    p.index=pd.to_datetime(p.index);b.index=pd.to_datetime(b.index)
    df=pd.concat([p.rename("p"),b.rename("b")],axis=1).dropna()
    if len(df)<30:return []
    rel=(df.p/df.b).apply(lambda x:100*math.log(x))
    rs=rel-rel.shift(12);mom=rs-rs.shift(4)
    xv=zscore(rs.tolist(),52);yv=zscore(mom.tolist(),52)
    return [{"date":d.strftime("%Y-%m-%d"),"x":round(100+v*5,3),"y":round(100+yv[i]*5,3)}
      for i,(d,v) in enumerate(zip(df.index,xv)) if v is not None and yv[i] is not None]
def main():
    OUT.mkdir(exist_ok=True)
    uni=json.loads((ROOT/"data/instrument_universe.json").read_text())["instruments"]
    instruments=[x for x in uni if x.get("yahoo") or x.get("id")]
    prices={};status={};batch_size=25
    for start in range(0,len(instruments),batch_size):
        batch=instruments[start:start+batch_size];syms=[x.get("yahoo") or x.get("id") for x in batch]
        try:
            raw=yf.download(tickers=syms,period="2y",interval="1d",auto_adjust=True,progress=False,threads=False,group_by="ticker",timeout=30)
        except Exception as e:
            for sym in syms:status[sym]="ERROR:"+str(e)[:100]
            continue
        for sym in syms:
            c=extract_close(raw,sym)
            if c is None or len(c)<30:status[sym]="NO_DATA";continue
            w=weekly(c)
            if len(w)<30:status[sym]="SHORT_HISTORY";continue
            prices[sym]={d.strftime("%Y-%m-%d"):float(v) for d,v in w.items()}
            status[sym]="OK"
    bench_series={}
    try:
        raw=yf.download(tickers=list(BENCH),period="2y",interval="1d",auto_adjust=True,progress=False,threads=False,group_by="ticker",timeout=30)
        for sym in BENCH:
            c=extract_close(raw,sym)
            if c is not None and len(c)>=30:bench_series[sym]={d.strftime("%Y-%m-%d"):float(v) for d,v in weekly(c).items()}
    except Exception as e:print("Benchmark batch failed:",str(e)[:180])
    fallback={"DBC":["WCOA.MI","WCOG.L","WCOE.MI"],"GLD":["SGLD.MI","WGLD.MI","SGBS.MI"]}
    for key,choices in fallback.items():
        if not bench_series.get(key):
            for ticker in choices:
                if ticker in prices:
                    bench_series[key]=prices[ticker];BENCH[key]=BENCH[key]+" (proxy "+ticker+")";print("Proxy",key,ticker);break
    inst={}
    for m in instruments:
        sym=m.get("yahoo") or m.get("id")
        if sym not in prices:continue
        cat=m.get("classification","");commodity=cat.startswith("MATERIE_PRIME")
        lev=float(m.get("leverage") or 1);short=bool(m.get("short")) or cat in ("LEVA_SHORT","MATERIE_PRIME_SHORT")
        inst[sym]={"ticker":m.get("ticker") or sym,"name":m.get("name") or sym,"category":cat,
          "leverage":lev,"commodity":commodity,"short":short,"rrg":{}}
        for bench,bs in bench_series.items():inst[sym]["rrg"][bench]=make_points(prices[sym],bs)
    payload={"generated_utc":pd.Timestamp.now(tz="UTC").isoformat(),"source":"Yahoo Finance adjusted weekly closes; RRG approximation, not proprietary JdK",
      "benchmarks":BENCH,"benchmark_prices":bench_series,"instruments":inst,
      "fetch_status":{"total":len(instruments),"ok":len(prices),"unavailable":len(instruments)-len(prices)},
      "method":{"RS":"12-week relative log return","RS-Momentum":"4-week change in RS","normalization":"rolling 52-week z-score, clipped +/-4, centered 100, scale 5"}}
    path=OUT/"sniper_rrg.json";path.write_text(json.dumps(payload,separators=(",",":"),ensure_ascii=False)+"\n",encoding="utf-8")
    category_counts={}
    benchmark_stats={}
    for x in inst.values():
        category_counts[x["category"]]=category_counts.get(x["category"],0)+1
    for b in BENCH:
        arr=[p for x in inst.values() for p in x["rrg"].get(b,[])]
        benchmark_stats[b]={"instruments_with_points":sum(bool(x["rrg"].get(b)) for x in inst.values()),"points":len(arr),"latest":max((p["date"] for p in arr),default=None)}
    summary={"generated_utc":payload["generated_utc"],"instruments":len(inst),"category_counts":category_counts,
      "benchmark_stats":benchmark_stats,"fetch_status":payload["fetch_status"],"benchmark_labels":BENCH,"method":payload["method"]}
    (OUT/"sniper_rrg_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    npoints=benchmark_stats.get("SPY",{}).get("points",0)
    print(f"Sniper RRG: {len(inst)} instruments; {npoints} weekly points vs SPY; benchmarks={list(bench_series)}; report={path.stat().st_size} bytes")
if __name__=="__main__":main()
