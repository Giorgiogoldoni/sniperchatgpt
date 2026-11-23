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

## Sicurezza e limiti
- PAPER ONLY: nessun broker, API di esecuzione o ordine reale.
- Una sola posizione aperta per strumento.
- Storico minimo richiesto: 60 barre giornaliere.
- Il primo avvio usa lo storico solo per inizializzare gli indicatori; crea segnali soltanto sull'ultima barra disponibile.
- I risultati sono lordi: spread, commissioni, slippage, imposte e liquidità effettiva non sono simulati nella v1.
- I dati Yahoo Finance possono essere incompleti o non disponibili per alcuni listing. Un ticker non validato resta escluso dal processo, non viene rimpiazzato silenziosamente.

## Avvio locale
```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python run.py
```

## Stato del progetto
Prima versione infrastrutturale. Il workflow automatico esegue i test; il motore PAPER è manuale e resta disattivato fino al completamento dei backtest per famiglia. La prima scansione esplorativa è conservata in `data/initial_scan_snapshot.json` e non rappresenta ordini o posizioni.

Non considerare la strategia validata: occorrono test, backtest separati per famiglia e controllo della qualità dei dati prima di usare il paper trading come riferimento operativo.
