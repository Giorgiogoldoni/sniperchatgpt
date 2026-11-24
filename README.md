# sniperchatgpt

Motore indipendente di analisi e **paper trading** per ETF/ETP a leva long, ETF/ETP a leva short/inversi e strumenti su materie prime.

## Universo iniziale
Importato dal censimento tecnico del repository `Giorgiogoldoni/sniper` (311 strumenti, con classificazioni originali conservate):
- `LEVA_LONG`
- `LEVA_SHORT`
- `MATERIE_PRIME_1X`
- `MATERIE_PRIME_LEVA`
- `MATERIE_PRIME_SHORT`

L'universo è in `data/instrument_universe.json`. Il mapping Yahoo Finance non è considerato automaticamente valido: strumenti con storico insufficiente vengono segnalati e saltati, senza inventare prezzi o sostituire la quotazione.

## Strategia v1
Tutti gli strumenti sono acquistati come ETP (anche quelli short/inversi): non vengono aperte vendite allo scoperto sul sottostante.

1. Segnale sulla candela giornaliera completata.
2. **Donchian 20**: close sopra il massimo delle 20 sedute precedenti (la seduta corrente è esclusa).
3. **Walking on the Upper Bollinger Band**: almeno 2 delle ultime 3 sedute con close entro l'1,5% dalla Bollinger superiore (20, 2), close sopra la media e banda superiore crescente.
4. Entrata PAPER all'open della seduta successiva.
5. Stop iniziale: prezzo d'ingresso meno 2 × ATR(14), calcolato alla data del segnale.
6. Uscita PAPER all'open dopo 2 chiusure consecutive senza Walking.
7. Permanenza massima: 10 sedute; uscita alla chiusura della decima.

Gli indicatori sono calcolati sull'OHLC dello **strumento negoziato**, non sul sottostante.

## Motore parallelo Mean Reversion (MR) — sperimentale

Il motore MR è separato dal Trend Following: non legge i segnali TF, non condivide posizioni e non combina condizioni dei due sistemi. Sono confrontate quattro varianti MR indipendenti (A, B, C, D), senza attivazione PAPER.

1. **A — baseline:** chiusura sotto la Bollinger inferiore (20, 2) e RSI(2) <= 10 sulla stessa seduta; ingresso all’open successivo.
2. **B — recupero:** dopo il setup A, attende almeno 2 chiusure su 3 sopra la banda inferiore; ingresso all’open successivo alla conferma. Se non conferma entro 3 sedute, il setup decade.
3. **C — Walking ribassista:** richiede il setup A, almeno 2 delle ultime 3 chiusure entro ±1,5% dalla banda inferiore e banda inferiore discendente nelle ultime 2 transizioni; ingresso all’open successivo.
3. Stop iniziale: prezzo d'ingresso meno 2 × ATR(14), calcolato alla data del segnale.
4. Uscita: alla chiusura quando il prezzo raggiunge/supera la Bollinger centrale; in alternativa stop ATR o massimo 10 sedute.
4. Gestione comune: stop iniziale 2 × ATR(14), uscita alla Bollinger centrale, stop o massimo 10 sedute.
5. Costi: scenari round trip 20 / 30 / 50 bps.

Il segnale MR è calcolato autonomamente sullo stesso OHLC aggiustato dello strumento negoziato. Il primo test con conferma del rientro sopra la banda ha prodotto zero segnali ed è stato scartato come troppo restrittivo; la versione attuale testa l'ingresso classico sull'eccesso. Gli esiti A/B/C/D sono confrontati in `reports/mr_backtest_summary.json`; le operazioni sono in `reports/mr_backtest_trades.csv` (A), `reports/mr_backtest_trades_b.csv` (B), `reports/mr_backtest_trades_c.csv` (C) e `reports/mr_backtest_trades_d.csv` (D). La dashboard distingue i marcatori TF (verde) e MR (blu): ogni ingresso è collocato al prezzo effettivo, con segmento orizzontale fino alla data di uscita. I due livelli possono essere nascosti separatamente.

La regola MR è una prima ipotesi di ricerca, non una strategia validata. In particolare, il rientro dalla banda inferiore può essere un falso rimbalzo in un mercato ribassista; stop, costi, liquidità, leva e risultati per famiglia devono essere verificati prima di qualunque utilizzo PAPER.

### Primo backtest MR — 24 novembre 2026

Su 255 strumenti con dati validi, la regola MR ha generato 2.348 operazioni. A 30 bps round trip: win rate 38,07%, media netta -0,529%, mediana -1,324%, profit factor 0,860. Il drawdown medio per strumento è -20,94%; il peggiore -86,31%. Non è un portafoglio simulato.

| Famiglia | Operazioni | Media netta | Mediana | Profit factor | DD medio strumenti |
|---|---:|---:|---:|---:|---:|
| Leva long | 472 | +0,525% | -2,325% | 1,071 | -35,90% |
| Leva short/inversi | 610 | +0,382% | -0,392% | 1,141 | -15,57% |
| Materie prime 1x | 880 | -0,982% | -1,701% | 0,554 | -13,13% |
| Materie prime leva | 216 | -2,753% | -3,769% | 0,528 | -32,85% |
| Materie prime short | 170 | -1,553% | -1,864% | 0,504 | -28,58% |

Lettura critica: il risultato aggregato è negativo; le medie leggermente positive nelle famiglie a leva long e short/inverse convivono con mediane negative e drawdown molto elevati. Sono quindi probabilmente influenzate da una coda di grandi vincite e non dimostrano un vantaggio robusto. Le categorie materie prime risultano deboli. Nessuna strategia MR è stata attivata in PAPER.

## Sicurezza e limiti
- PAPER ONLY: nessun broker, API di esecuzione o ordine reale.
- Una sola posizione aperta per strumento.
- Storico minimo richiesto: 60 barre giornaliere.
- Il primo avvio usa lo storico solo per inizializzare gli indicatori; crea segnali soltanto sull'ultima barra disponibile.
- I risultati sono lordi: spread, commissioni, slippage, imposte e liquidità effettiva non sono simulati nella v1.
- I dati Yahoo Finance possono essere incompleti o non disponibili per alcuni listing. Un ticker non validato resta escluso dal processo, non viene rimpiazzato silenziosamente.

## Dashboard e report
- Dashboard: [index.html](index.html) (pubblicazione GitHub Pages da abilitare una sola volta in Settings → Pages → Build and deployment → Source: GitHub Actions).
- Workbook: [reports/sniperchatgpt_backtest.xlsx](reports/sniperchatgpt_backtest.xlsx).
- Sintesi dati: [reports/backtest_summary.json](reports/backtest_summary.json).
- Operazioni simulate: [reports/backtest_trades.csv](reports/backtest_trades.csv).
- Audit qualità dati: [reports/backtest_data_audit.csv](reports/backtest_data_audit.csv).

## Primo backtest storico — 23 novembre 2026
Finestra richiesta: 2 anni di barre giornaliere Yahoo Finance, OHLC aggiustati. Universo censito: 311 strumenti; dati sufficienti e non anomali: 255; esclusi per storico assente/insufficiente o discontinuità prezzo: 56 (di cui 29 sospetti); errori di download: 0. Operazioni simulate: 2.696. Scenari di costo round trip: 20, 30 e 50 bps.

| Famiglia | Dati validi | Operazioni | Win rate | Media netta a 30 bps | Profit factor |
|---|---:|---:|---:|---:|---:|
| Leva long | 52/73 | 417 | 41,97% | -0,297% | 0,928 |
| Leva short | 61/86 | 521 | 29,56% | -0,868% | 0,686 |
| Materie prime 1x | 106/108 | 1.426 | 40,46% | +0,052% | 1,033 |
| Materie prime leva long | 24/26 | 233 | 40,77% | +1,078% | 1,258 |
| Materie prime short | 12/18 | 99 | 30,30% | -0,080% | 0,959 |

Le statistiche sono per operazione e per famiglia, non simulano un portafoglio con capitale, posizioni concorrenti e sizing. Il drawdown mostrato nei report è calcolato per singolo strumento; non è un drawdown di portafoglio. I dati anomali sono esclusi con filtro di variazione giornaliera superiore a +300% o inferiore a -80%, da verificare singolarmente prima di eventuale reinclusione. 3OIS.MI non ha restituito barre OHLC nel download: rimane escluso.

Questi numeri sono diagnostici, non validano la strategia. In particolare leva long, leva short e materie prime short non superano il primo controllo a 30 bps. Nessun motore PAPER è stato attivato.

## Avvio locale
```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python run.py
```

## Stato del progetto
Prima versione infrastrutturale. Il workflow automatico esegue prima i test unitari e poi il backtest; il motore PAPER è manuale e resta disattivato fino al completamento dei backtest per famiglia. La prima scansione esplorativa è conservata in `data/initial_scan_snapshot.json` e non rappresenta ordini o posizioni.

Non considerare la strategia validata: occorrono test, backtest separati per famiglia e controllo della qualità dei dati prima di usare il paper trading come riferimento operativo.
