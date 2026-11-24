#!/usr/bin/env python3
"""Create a multi-sheet Excel workbook from the latest historical backtest."""
import json
from pathlib import Path
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
ROOT=Path(__file__).resolve().parent; R=ROOT/"reports"
summary=json.loads((R/"backtest_summary.json").read_text(encoding="utf-8"))
mr_summary=json.loads((R/"mr_backtest_summary.json").read_text(encoding="utf-8"))
wb=Workbook(); ws=wb.active; ws.title="Sintesi"
for row in [
["SNIPERCHATGPT — BACKTEST STORICO"],["Generato UTC",summary["generated_utc"]],
["Universo",summary["universe_total"]],["Dati utilizzabili",summary["data_ok"]],
["Esclusi",summary["skipped"]],["Prezzi sospetti",summary.get("suspicious",0)],["Errori",summary["errors"]],
["Operazioni simulate",summary["trades_total"]],["Metodo",summary["method"]],[],
["Categoria","Universo","Dati OK","Esclusi","Errori","Trade","Win rate %","Media netta %","Profit factor","Drawdown medio strumenti %"]
]: ws.append(row)
for x in summary["families"]:
    k="net_30bps_pct"
    ws.append([x["category"],x["universe"],x["data_ok"],x["skipped"],x["errors"],x.get(k+"_trades",0),
               x.get(k+"_win_rate_pct",0),x.get(k+"_avg_net_pct",0),x.get(k+"_profit_factor",0),x.get(k+"_avg_instrument_drawdown_pct",0)])
def add_frame(name,path):
    if path.exists():
        try:
            frame=pd.read_csv(path).fillna("")
        except pd.errors.EmptyDataError:
            frame=pd.DataFrame()
        sh=wb.create_sheet(name)
        if frame.empty:
            sh.append(["Nessuna operazione disponibile nel report corrente"])
        else:
            sh.append(list(frame.columns))
            for row in frame.itertuples(index=False,name=None): sh.append(list(row))
add_frame("Audit strumenti",R/"backtest_data_audit.csv")
add_frame("Operazioni TF",R/"backtest_trades.csv")
add_frame("Operazioni MR A",R/"mr_backtest_trades.csv")
add_frame("Operazioni MR B",R/"mr_backtest_trades_b.csv")
add_frame("Operazioni MR C",R/"mr_backtest_trades_c.csv")
add_frame("Operazioni MR D",R/"mr_backtest_trades_d.csv")
variants=mr_summary.get("variants",{})
if variants:
    comp=wb.create_sheet("Confronto MR A-B-C-D")
    comp.append(["VARIANTE","COSTI BPS","OPERAZIONI","WIN RATE %","MEDIA NETTA %","MEDIANA NETTA %","PROFIT FACTOR","DD MEDIO STRUMENTI %","PEGGIOR DD STRUMENTO %"])
    for variant, data in variants.items():
        for bps, m in data["costs"].items():
            if bps == "exposure":
                continue
            comp.append([variant,int(bps),m["trades"],m["win_rate_pct"],m["avg_net_pct"],m["median_net_pct"],m["profit_factor"],m["avg_instrument_drawdown_pct"],m["worst_instrument_drawdown_pct"]])
    exposure=variants.get("D",{}).get("costs",{}).get("exposure",{})
    if exposure:
        comp.append([])
        comp.append(["MR-D ESPOSIZIONE","Media capitale investito %","Trade con 100% investito %","Media tranche per trade","Trade 1 tranche","Trade 2 tranche","Trade 3 tranche"])
        comp.append(["D",exposure.get("avg_deployed_weight_pct"),exposure.get("full_deployment_trades_pct"),exposure.get("avg_tranches_per_trade"),exposure.get("one_tranche_trades"),exposure.get("two_tranche_trades"),exposure.get("three_tranche_trades")])

mr=wb.create_sheet("Sintesi MR")
mr.append(["MEAN REVERSION — MOTORE INDIPENDENTE"])
mr.append(["Costi round trip bps","Operazioni","Win rate %","Media netta %","Mediana netta %","Profit factor","DD medio strumenti %","Peggior DD strumento %"])
for bps,m in mr_summary["costs"].items(): mr.append([int(bps),m["trades"],m["win_rate_pct"],m["avg_net_pct"],m["median_net_pct"],m["profit_factor"],m["avg_instrument_drawdown_pct"],m["worst_instrument_drawdown_pct"]])
mr.append([])
mr.append(["Regola","Descrizione"])
for key,value in mr_summary["rules"].items(): mr.append([key,str(value)])
rules=wb.create_sheet("Regole")
for row in [
["Parametro","Regola v1"],["Universo","ETF/ETP leva long, leva short/inversi e materie prime"],
["Motori","Trend Following e Mean Reversion indipendenti; nessuna combinazione dei segnali"],
["MR segnale","Close sotto Bollinger inferiore (20,2) e RSI(2) <= 10 sulla stessa seduta"],
["MR ingresso","Segnale a chiusura; ingresso all’open successivo"],
["MR-D","40% all’ingresso A; 30% + 30% su due nuovi Walking inferiori confermati dopo l’ingresso; stop iniziale fisso, non allargato dagli incrementi; massimo 100%"],
["MR uscita","Chiusura alla Bollinger centrale; stop 2 x ATR(14); massimo 10 sedute"],
["Donchian","Close > massimo High delle 20 sedute precedenti"],
["Walking","Almeno 2 delle ultime 3 sedute: close entro 1,5% dalla Bollinger superiore 20,2; close sopra media e banda superiore crescente"],
["Ingresso","Open della seduta successiva al segnale"],["Stop iniziale","Prezzo ingresso - 2 x ATR(14) calcolato alla data segnale"],
["Uscita Walking","Dopo 2 close consecutivi senza Walking, all'open successivo"],
["Durata massima","10 sedute; uscita al close della decima"],["Costi","Scenari 20 / 30 / 50 bps round trip"],
["Avvertenza","Simulazione storica, non promessa di rendimento né ordine reale"]
]: rules.append(row)
for sh in wb.worksheets:
    sh.freeze_panes="A2"; sh.auto_filter.ref=sh.dimensions
    for cell in sh[1]:
        cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="17365D")
        cell.alignment=Alignment(wrap_text=True,vertical="center")
    for col in sh.columns:
        vals=[len(str(c.value or "")) for c in list(col)[:250]]
        sh.column_dimensions[get_column_letter(col[0].column)].width=min(max(max(vals,default=10)+2,12),48)
    sh.sheet_view.showGridLines=False
wb.save(R/"sniperchatgpt_backtest.xlsx")
