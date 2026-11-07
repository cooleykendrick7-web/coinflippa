# COINFLIPPA — Crypto Flipper

Spelled **C-O-I-N-F-L-I-P-P-A**. Ken's standalone crypto flipping app
(FastAPI + SQLite, no-password board like ClaimBoard / RUNNAUP / Workspace).
The standalone version of the COINFLIPPA dashboard — installable on his phone
home screen (PWA) like HERE.

## What it does
- **My Coinbase Account** — Ken's REAL Coinbase balances as a dated snapshot
  (read read-only in the browser Sat Nov 7, 2026, 4:15 PM CT; total $10.70).
  It is a snapshot, **not** a live Coinbase feed — no live Coinbase connection
  exists and none is claimed anywhere in the app.
- **Live prices** — BTC, ETH, SOL, LINK, AVAX, XRP, DOGE fetched server-side
  from the public CoinGecko API (cached ~5 minutes, saved to the DB).
- **The Pot** — money in/out, free cash, current value, profit/loss from
  recorded flips only. No fake profit.
- **Today's stance** — computed from 30-day price changes
  (red market = "Small and patient").
- **Proposals** — real-move proposals with plain-English WHAT / WHY / HOW /
  RISK / EXIT. Ken makes the move himself in Coinbase and taps
  "I did this in Coinbase" (logs the flip), or skips it.
- **/database** — the visible database: every table's real rows in plain
  English, exactly as saved.

## Engine rules (in code)
- No flip under **$10** of free pot cash — fees would eat it
  (`suggest_move()` refuses and says why, in plain words).
- One waiting proposal at a time.
- This app never logs into Coinbase, never trades, never moves money.

## Run
```
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port $PORT   # DB path: $COINFLIPPA_DB or ./coinflippa.db
```
Render: see `render.yaml` (Starter plan, 1 GB persistent disk at /data).
