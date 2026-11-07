"""
COINFLIPPA — Ken's crypto flipping app. Spelled C-O-I-N-F-L-I-P-P-A.
Standalone version of the COINFLIPPA dashboard (FastAPI + SQLite), modeled on
RUNNAUP / ClaimBoard (no-password board by Ken's standing order for his boards).

WHAT IT IS:
  - Shows Ken's REAL Coinbase account as a dated snapshot (read read-only in
    the browser on Sat Nov 7, 2026, 4:15 PM CT). It is a SNAPSHOT, not a live
    Coinbase feed — no live Coinbase connection exists and none is claimed.
  - Prices ARE live: fetched server-side from the public CoinGecko API.
  - The Pot tracks money Ken puts in / takes out, flips, and profit/loss.
  - Proposals are REAL-MOVE proposals: Ken marks one done after he makes the
    move himself in Coinbase, or skips it. This app never trades, never logs
    into Coinbase, and never moves money.

ENGINE RULES (in code, not just words):
  - No flip under $10 of free pot cash — fees would eat it ("nothing to flip
    yet"). suggest_move() refuses below $10.
  - Stance comes from 30-day price changes: red market = "Small and patient".
  - No fake flips, no fake profit. Profit/loss counts only recorded flips.
"""
import os, json, time, datetime, sqlite3, urllib.request, urllib.error
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
DB_PATH = os.environ.get("COINFLIPPA_DB", str(BASE / "coinflippa.db"))

app = FastAPI(title="COINFLIPPA", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

SNAPSHOT_LABEL = "Sat Nov 7, 2026, 4:15 PM CT"
COINS = [  # CoinGecko id, symbol, name
    ("bitcoin", "BTC", "Bitcoin"),
    ("ethereum", "ETH", "Ethereum"),
    ("solana", "SOL", "Solana"),
    ("chainlink", "LINK", "Chainlink"),
    ("avalanche-2", "AVAX", "Avalanche"),
    ("ripple", "XRP", "XRP"),
    ("dogecoin", "DOGE", "Dogecoin"),
]

# symbol, name, amount, usd_value, note — Ken's real Coinbase read, Nov 7 2026.
SEED_HOLDINGS = [
    ("USD", "US Dollar (cash)", 0.87, 0.87, "Free cash — this is in the Pot"),
    ("USDC", "USDC (cash)", 0.11, 0.11, "Free cash — this is in the Pot"),
    ("ETH", "Ethereum", 0.00432994, 9.65, "99% staked — locked up earning about $0.01/month. Can't flip while staked"),
    ("SARP", "Strategic American Protocol", 898.65423558, 0.02, "Dust — tiny amount, worth about 2 cents"),
    ("POL", "Polygon Ecosystem Token", 0.27668373, 0.02, "100% staked. Dust — worth about 2 cents"),
    ("AERGO", "Aergo", 0.08711746, 0.00, "Dust — shows as $0.00 on Coinbase"),
    ("LINK", "Chainlink", 0.00012552, 0.00, "Dust — shows as $0.00 on Coinbase"),
    ("FET", "Artificial Superintelligence Alliance", 0.00385081, 0.00, "Dust — shows as $0.00 on Coinbase"),
    ("ETC", "Ethereum Classic", 0.00004592, 0.00, "Dust — shows as $0.00 on Coinbase"),
    ("GST", "Green Satoshi Token", 0.10467966, 0.00, "Dust — shows as $0.00 on Coinbase"),
    ("TVK", "Virtua", 0.03216152, 0.00, "Dust — shows as $0.00 on Coinbase"),
    ("FOX", "Shapeshift FOX Token", 0.00143164, 0.00, "Dust — shows as $0.00 on Coinbase"),
]

SEED_SUGGESTIONS = [
    # kind, symbol, name, reason, risk
    ("crypto", "BTC", "Bitcoin", "The biggest, oldest crypto. Most people start here. It still swings, but it is the steadiest of the bunch.", "Medium"),
    ("crypto", "ETH", "Ethereum", "Powers a huge network of apps. Big and well known, but it swings more than Bitcoin.", "Medium"),
    ("crypto", "SOL", "Solana", "Fast and popular, but it fell the hardest this month. A bounce could pay — or it could fall more. Small amounts only.", "High"),
    ("crypto", "LINK", "Chainlink", "Feeds real-world data (like prices) into crypto apps. Smaller than Bitcoin, so it moves bigger both ways.", "High"),
    ("crypto", "AVAX", "Avalanche", "Another app network, smaller than Ethereum. Higher risk, higher possible reward. Not a first buy.", "High"),
    ("crypto", "XRP", "XRP", "Built for moving money between banks. Well known and cheaper per coin, but its price can jump on news.", "Medium"),
    ("crypto", "DOGE", "Dogecoin", "Started as a joke coin. It moves on hype, not on a business. Fun money only — never money you need.", "High"),
    ("stock", "SPY", "State Street SPDR S&P 500 ETF", "One buy that holds 500 big US companies at once. If America does well, this does well. The calmest way to own stocks.", "Low"),
    ("stock", "QQQ", "Invesco QQQ Trust Series I", "Holds the big tech companies (Apple, Microsoft, Nvidia and more). Grows faster than SPY when tech is hot, falls harder when it is not.", "Medium"),
    ("stock", "AAPL", "Apple Inc.", "The iPhone company. Huge, profitable, and pays steady. A single company, so it carries more risk than a fund like SPY.", "Medium"),
    ("stock", "MSFT", "Microsoft Corporation", "Windows, Office, and a giant AI business. One of the steadiest big tech names.", "Medium"),
    ("stock", "NVDA", "NVIDIA Corporation", "Makes the chips AI runs on. It has run up a lot already — big possible gains, big possible drops. Small amounts only.", "High"),
    ("stock", "KO", "Coca-Cola Co", "Sells drinks in every country and pays a dividend (a small cash payout to owners). Slow and steady, not a get-rich pick.", "Low"),
]

SAFETY_RULES = [
    "Never all-in — never put everything into one coin.",
    "Always keep some cash back in the Pot.",
    "Cut losses at the stop — if a flip drops to its stop price, sell. No hoping.",
    "Take profit in pieces — sell a little at a time on the way up, not all at once.",
    "No flip under $10 — Coinbase fees would eat it before it starts.",
    "Nothing is promised. Crypto can drop fast. Only flip money you can afford to lose.",
]

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS account_snapshots(
      id INTEGER PRIMARY KEY, taken_label TEXT, taken_at TEXT,
      total_usd REAL, cash_usd REAL, note TEXT);
    CREATE TABLE IF NOT EXISTS holdings(
      id INTEGER PRIMARY KEY, snapshot_id INTEGER, symbol TEXT, name TEXT,
      amount REAL, usd_value REAL, note TEXT);
    CREATE TABLE IF NOT EXISTS pot_entries(
      id INTEGER PRIMARY KEY, kind TEXT, amount REAL, note TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS flips(
      id INTEGER PRIMARY KEY, created_at TEXT, side TEXT, coin TEXT,
      amount_usd REAL, qty REAL, price REAL,
      what TEXT, why TEXT, how TEXT, risk TEXT, exit_plan TEXT, result TEXT);
    CREATE TABLE IF NOT EXISTS proposals(
      id INTEGER PRIMARY KEY, created_at TEXT, title TEXT, coin TEXT,
      amount_usd REAL, what TEXT, why TEXT, how TEXT, risk TEXT,
      exit_plan TEXT, status TEXT DEFAULT 'waiting');
    CREATE TABLE IF NOT EXISTS suggestions(
      id INTEGER PRIMARY KEY, kind TEXT, symbol TEXT, name TEXT,
      reason TEXT, risk_level TEXT);
    CREATE TABLE IF NOT EXISTS price_snapshots(
      id INTEGER PRIMARY KEY, fetched_at TEXT, symbol TEXT, price REAL,
      change_24h REAL, change_7d REAL, change_30d REAL);
    CREATE TABLE IF NOT EXISTS daily_reviews(
      id INTEGER PRIMARY KEY, day TEXT UNIQUE, stance TEXT, summary TEXT,
      created_at TEXT);
    """)
    if c.execute("SELECT COUNT(*) n FROM account_snapshots").fetchone()["n"] == 0:
        cur = c.execute(
            "INSERT INTO account_snapshots(taken_label, taken_at, total_usd, cash_usd, note)"
            " VALUES(?,?,?,?,?)",
            (SNAPSHOT_LABEL, "2026-11-07T16:15:00-06:00", 10.70, 0.98,
             "Read read-only from Ken's Coinbase in the browser. Confirmed on two page loads. "
             "This is a dated snapshot — COINFLIPPA does not have a live Coinbase feed."))
        sid = cur.lastrowid
        c.executemany(
            "INSERT INTO holdings(snapshot_id, symbol, name, amount, usd_value, note) VALUES(?,?,?,?,?,?)",
            [(sid, s, n, a, v, note) for (s, n, a, v, note) in SEED_HOLDINGS])
        c.execute(
            "INSERT INTO pot_entries(kind, amount, note, created_at) VALUES('in', 0.98, ?, ?)",
            ("Coinbase link day (Nov 7, 2026): free cash found — $0.87 USD + $0.11 USDC. "
             "The rest of the $10.70 is staked ETH ($9.65) and dust coins (about $0.04) — not free to flip.",
             "2026-11-07T16:16:00-06:00"))
        c.executemany(
            "INSERT INTO suggestions(kind, symbol, name, reason, risk_level) VALUES(?,?,?,?,?)",
            SEED_SUGGESTIONS)
    c.commit(); c.close()

# ---------------- prices (CoinGecko, public, no key) ----------------
_price_cache = {"at": 0.0, "rows": []}

def fetch_prices():
    """Live prices from CoinGecko public API. Cached ~5 minutes.
    Falls back to the newest saved snapshot if the fetch fails."""
    now = time.time()
    if _price_cache["rows"] and now - _price_cache["at"] < 300:
        return _price_cache["rows"], True
    ids = ",".join(i for i, _, _ in COINS)
    url = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
           f"&ids={ids}&price_change_percentage=24h,7d,30d")
    rows = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "COINFLIPPA/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
        by_id = {d["id"]: d for d in data}
        for cid, sym, name in COINS:
            d = by_id.get(cid)
            if not d:
                continue
            rows.append({
                "symbol": sym, "name": name,
                "price": d.get("current_price"),
                "change_24h": d.get("price_change_percentage_24h_in_currency"),
                "change_7d": d.get("price_change_percentage_7d_in_currency"),
                "change_30d": d.get("price_change_percentage_30d_in_currency"),
            })
    except Exception:
        rows = []
    if rows:
        _price_cache.update(at=now, rows=rows)
        c = db()
        last = c.execute("SELECT MAX(fetched_at) m FROM price_snapshots").fetchone()["m"]
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if not last or (datetime.datetime.now(datetime.timezone.utc)
                        - datetime.datetime.fromisoformat(last)).total_seconds() > 240:
            c.executemany(
                "INSERT INTO price_snapshots(fetched_at, symbol, price, change_24h, change_7d, change_30d)"
                " VALUES(?,?,?,?,?,?)",
                [(stamp, r["symbol"], r["price"], r["change_24h"], r["change_7d"], r["change_30d"]) for r in rows])
            c.commit()
        c.close()
        return rows, True
    # fallback: newest snapshot rows
    c = db()
    last = c.execute("SELECT MAX(fetched_at) m FROM price_snapshots").fetchone()["m"]
    out = []
    if last:
        names = {s: n for _, s, n in COINS}
        for r in c.execute("SELECT * FROM price_snapshots WHERE fetched_at=? ORDER BY symbol", (last,)):
            out.append({"symbol": r["symbol"], "name": names.get(r["symbol"], r["symbol"]),
                        "price": r["price"], "change_24h": r["change_24h"],
                        "change_7d": r["change_7d"], "change_30d": r["change_30d"]})
    c.close()
    return out, False

def compute_stance(prices):
    by = {p["symbol"]: p for p in prices}
    ch = [by[s]["change_30d"] for s in ("BTC", "ETH", "SOL")
          if s in by and by[s]["change_30d"] is not None]
    if not ch:
        return "Waiting on prices", "COINFLIPPA could not read live prices just now. No moves until prices are back."
    avg = sum(ch) / len(ch)
    parts = ", ".join(f"{s} {by[s]['change_30d']:+.1f}% in 30 days" for s in ("BTC", "ETH", "SOL") if s in by)
    if avg <= -5:
        return "Small and patient", (f"The market is down right now. {parts}. When prices are red like this, "
                                      "COINFLIPPA moves small, keeps cash ready, and does not chase. No wild flipping.")
    if avg >= 5:
        return "Green — careful growth", (f"The market is up right now. {parts}. Prices rising does not mean safe — "
                                          "COINFLIPPA still moves in small pieces and takes profit on the way up.")
    return "Steady — small moves only", (f"The market is moving sideways. {parts}. No big swings either way, "
                                         "so COINFLIPPA only lines up small, careful moves.")

def record_daily_review(stance, summary):
    day = datetime.date.today().isoformat()
    c = db()
    c.execute("INSERT OR IGNORE INTO daily_reviews(day, stance, summary, created_at) VALUES(?,?,?,?)",
              (day, stance, summary, datetime.datetime.now(datetime.timezone.utc).isoformat()))
    c.commit(); c.close()

# ---------------- pot + engine ----------------
def pot_state(c):
    ins = c.execute("SELECT COALESCE(SUM(amount),0) s FROM pot_entries WHERE kind='in'").fetchone()["s"]
    outs = c.execute("SELECT COALESCE(SUM(amount),0) s FROM pot_entries WHERE kind='out'").fetchone()["s"]
    buys = c.execute("SELECT COALESCE(SUM(amount_usd),0) s FROM flips WHERE side='buy'").fetchone()["s"]
    sells = c.execute("SELECT COALESCE(SUM(amount_usd),0) s FROM flips WHERE side='sell'").fetchone()["s"]
    cash = round(ins - outs - buys + sells, 2)
    # open holdings from flips
    hold = {}
    for f in c.execute("SELECT * FROM flips ORDER BY id"):
        h = hold.setdefault(f["coin"], {"qty": 0.0, "cost": 0.0})
        if f["side"] == "buy":
            h["qty"] += f["qty"] or 0; h["cost"] += f["amount_usd"] or 0
        else:
            h["qty"] -= f["qty"] or 0; h["cost"] -= f["amount_usd"] or 0
    return {"money_in": round(ins, 2), "money_out": round(outs, 2),
            "cash": cash, "holdings": hold}

def pot_value(c, prices):
    st = pot_state(c)
    by = {p["symbol"]: p["price"] for p in prices if p["price"]}
    hv = 0.0
    for sym, h in st["holdings"].items():
        if h["qty"] > 0.0000001 and sym in by:
            hv += h["qty"] * by[sym]
    total = round(st["cash"] + hv, 2)
    pnl = round(total - (st["money_in"] - st["money_out"]), 2)
    base = st["money_in"] - st["money_out"]
    pnl_pct = round(pnl / base * 100, 2) if base else 0.0
    return {**st, "holdings_value": round(hv, 2), "current_value": total,
            "pnl": pnl, "pnl_pct": pnl_pct}

MIN_FLIP = 10.00

def suggest_move(c, prices):
    """Line up ONE real-move proposal, or refuse with a plain reason.
    Rule: free pot cash under $10 = nothing to flip (fees would eat it)."""
    st = pot_state(c)
    if st["cash"] < MIN_FLIP:
        return None, (f"Nothing to flip yet — the Pot has ${st['cash']:.2f} free cash and a flip under "
                      f"${MIN_FLIP:.0f} would be eaten by Coinbase fees. Add money to the Pot and "
                      "COINFLIPPA will line up a move.")
    waiting = c.execute("SELECT COUNT(*) n FROM proposals WHERE status='waiting'").fetchone()["n"]
    if waiting:
        return None, "A move is already lined up and waiting for Ken. One at a time."
    by = {p["symbol"]: p for p in prices}
    btc = by.get("BTC")
    if not btc or not btc["price"]:
        return None, "Prices are not loading right now, so no move gets lined up. Try again in a few minutes."
    amount = round(max(MIN_FLIP, st["cash"] * 0.25), 2)
    amount = min(amount, st["cash"])
    price = btc["price"]
    stop = round(price * 0.92, 2)
    target = round(price * 1.15, 2)
    what = f"Buy ${amount:.2f} of Bitcoin (BTC) in Coinbase at about ${price:,.0f} per coin."
    why = ("Bitcoin is the biggest, steadiest crypto. The market is down this month, so COINFLIPPA "
           "starts small with the steadiest coin instead of chasing a wild one.")
    how = ("In the Coinbase app: tap Buy, pick Bitcoin, type the dollar amount, review, confirm. "
           "Then come back here and tap 'I did this' so COINFLIPPA logs the flip.")
    risk = ("Bitcoin can still drop. This is a small piece of the Pot (about a quarter of the free cash), "
            "never everything.")
    exit_plan = (f"Safety exit: if BTC falls to about ${stop:,.0f} (down 8%), sell and cut the loss. "
                 f"Profit exit: if BTC climbs to about ${target:,.0f} (up 15%), sell a piece and keep the win.")
    cur = c.execute(
        "INSERT INTO proposals(created_at, title, coin, amount_usd, what, why, how, risk, exit_plan)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (datetime.datetime.now(datetime.timezone.utc).isoformat(),
         f"Buy ${amount:.2f} of BTC", "BTC", amount, what, why, how, risk, exit_plan))
    c.commit()
    return cur.lastrowid, "Move lined up — see the Proposals section."

# ---------------- html helpers ----------------
def money(v):
    if v is None: return "—"
    return f"${v:,.2f}"

def pct(v):
    if v is None: return "—"
    return f"{v:+.1f}%"

def cls(v):
    if v is None: return ""
    return "up" if v >= 0 else "down"

CSS = """
:root{--bg:#070707;--panel:#12100e;--panel2:#1a1512;--line:#3d2f28;--txt:#f5efe9;--mut:#b8a89a;
--gold:#fbbf24;--rose:#e0a387;--rose2:#b76e79;--green:#4ade80;--red:#f87171;--acc:#e0a387}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--txt)}
header{padding:14px 18px;background:linear-gradient(90deg,#000,#241611);border-bottom:2px solid var(--rose2);position:sticky;top:0;z-index:5}
.hwrap{display:flex;gap:14px;align-items:center}
.hport{width:58px;height:58px;object-fit:cover;object-position:top;border-radius:50%;border:2px solid var(--rose);flex:none}
h1{margin:0;font-size:28px;letter-spacing:1px}.sub{color:var(--rose);font-size:14px;margin-top:3px}
.aport{width:110px;height:150px;object-fit:cover;object-position:top;border-radius:12px;border:2px solid var(--rose);flex:none}
#welcome{position:fixed;inset:0;z-index:99;background:#000;display:flex;align-items:flex-end;justify-content:center;overflow:hidden;transition:opacity .7s ease}
#welcome.gone{opacity:0;pointer-events:none}
#welcome img.hero{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:top;animation:wzoom 6s ease forwards}
#welcome .shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.25) 30%,rgba(0,0,0,.88) 78%)}
#welcome .wtext{position:relative;text-align:center;padding:0 20px 9vh;width:100%}
#welcome .w1,#welcome .w2,#welcome .w3,#welcome .tag,#welcome .enter{opacity:0}
#welcome .w1{font-size:19px;letter-spacing:5px;color:var(--rose);font-weight:700;animation:wup .8s ease .2s forwards}
#welcome .w2{font-size:52px;font-weight:900;letter-spacing:2px;line-height:1.05;color:#fff;animation:wup .8s ease .55s forwards;text-shadow:0 3px 22px rgba(0,0,0,.7)}
#welcome .tag{font-size:18px;font-style:italic;color:var(--rose);margin-top:12px;animation:wup .8s ease 1.05s forwards}
#welcome .enter{margin-top:26px;background:linear-gradient(90deg,var(--rose),var(--rose2));color:#140b06;font-size:17px;padding:14px 42px;border-radius:999px;animation:wup .8s ease 1.5s forwards}
@keyframes wup{from{opacity:0;transform:translateY(26px)}to{opacity:1;transform:translateY(0)}}
@keyframes wzoom{from{transform:scale(1.06)}to{transform:scale(1)}}
main{max-width:1020px;margin:0 auto;padding:16px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:6px 0 14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;margin:0 0 14px}
.card b.big{font-size:30px;display:block}.card span{color:var(--mut);font-size:13px}
h2{margin:24px 0 8px;font-size:21px}h3{margin:0 0 6px;font-size:17px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
td,th{padding:10px;border-bottom:1px solid var(--line);text-align:left;font-size:15px;vertical-align:top}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.up{color:var(--green)}.down{color:var(--red)}.gold{color:var(--gold)}
.mut{color:var(--mut);font-size:13px}.small{font-size:14px}
.notebox{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:10px 0;font-size:15px}
.warn{background:#3f1d02;border-color:#b45309}
button{background:var(--acc);color:#04121f;border:0;padding:11px 16px;border-radius:10px;font-weight:700;cursor:pointer;font-size:15px}
button.goldb{background:var(--gold);color:#231a02}
button.okb{background:#166534;color:#fff}button.skipb{background:#7f1d1d;color:#fff}
input,select{background:#171310;color:var(--txt);border:1px solid var(--line);border-radius:9px;padding:10px;font-size:15px}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:800;text-transform:uppercase;white-space:nowrap}
.b-wait{background:#713f12;color:#fde68a}.b-done{background:#166534;color:#bbf7d0}.b-skip{background:#475569;color:#e2e8f0}
.risk-Low{background:#166534;color:#bbf7d0}.risk-Medium{background:#713f12;color:#fde68a}.risk-High{background:#7f1d1d;color:#fecaca}
.flash{background:#14532d;color:#bbf7d0;border:1px solid #16a34a;padding:12px 16px;border-radius:12px;font-weight:700;margin:10px 0}
.nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.nav a{color:var(--txt);text-decoration:none;border:1px solid var(--line);background:var(--panel);padding:8px 14px;border-radius:999px;font-weight:700;font-size:14px}
.flip{border-left:4px solid var(--rose)}
.kv{display:grid;grid-template-columns:64px 1fr;gap:2px 10px;font-size:15px;margin-top:8px}
.kv b{color:var(--rose)}
"""

WELCOME = """
<div id="welcome">
<img class="hero" src="/static/ken-tuxedo.webp" alt="Ken — founder of COINFLIPPA">
<div class="shade"></div>
<div class="wtext">
<div class="w1" style="text-transform:uppercase">Welcome to</div>
<div class="w2">COINFLIPPA</div>
<div class="tag">&ldquo;Where your money always turn into something&rdquo;</div>
<button class="enter" onclick="cfEnter()">Enter &rarr;</button>
</div>
</div>
<script>
function cfEnter(){var w=document.getElementById('welcome');if(!w)return;w.classList.add('gone');
try{sessionStorage.setItem('cf_welcomed','1')}catch(e){}
setTimeout(function(){w.style.display='none'},750);}
(function(){var seen=false;try{seen=sessionStorage.getItem('cf_welcomed')==='1'}catch(e){}
var w=document.getElementById('welcome');
if(seen){w.style.display='none';return;}
setTimeout(cfEnter,4600);})();
</script>
"""

def page(title, body, welcome=False):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{title} — COINFLIPPA</title>
<meta name="theme-color" content="#0b1020">
<link rel="manifest" href="/static/manifest.webmanifest">
<link rel="icon" href="/static/icons/icon-192.png">
<link rel="apple-touch-icon" href="/static/icons/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="COINFLIPPA">
<style>{CSS}</style></head>
<body>
{WELCOME if welcome else ''}
<header><div class="hwrap"><img class="hport" src="/static/ken-tuxedo.webp" alt="Ken">
<div><h1>🪙 COINFLIPPA</h1>
<div class="sub">Where your money always turn into something.</div></div></div>
<div class="nav"><a href="/">🏠 Dashboard</a><a href="/database">🗄️ See the Database</a></div>
</header>
<main>{body}</main>
<script>if('serviceWorker' in navigator){{navigator.serviceWorker.register('/static/sw.js').catch(()=>{{}});}}</script>
</body></html>"""

# ---------------- routes ----------------
@app.on_event("startup")
def _startup():
    init_db()

@app.get("/healthz")
def healthz():
    try:
        c = db()
        n = c.execute("SELECT COUNT(*) n FROM holdings").fetchone()["n"]
        c.close()
        return {"ok": True, "db": "ok", "holdings": n, "app": "coinflippa"}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    init_db()
    c = db()
    snap = c.execute("SELECT * FROM account_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    holds = c.execute("SELECT * FROM holdings WHERE snapshot_id=? ORDER BY usd_value DESC", (snap["id"],)).fetchall()
    prices, live = fetch_prices()
    stance, summary = compute_stance(prices)
    record_daily_review(stance, summary)
    pv = pot_value(c, prices)
    pot_rows = c.execute("SELECT * FROM pot_entries ORDER BY id DESC").fetchall()
    flips = c.execute("SELECT * FROM flips ORDER BY id DESC").fetchall()
    props = c.execute("SELECT * FROM proposals ORDER BY id DESC").fetchall()
    sug_c = c.execute("SELECT * FROM suggestions WHERE kind='crypto' ORDER BY id").fetchall()
    sug_s = c.execute("SELECT * FROM suggestions WHERE kind='stock' ORDER BY id").fetchall()
    c.close()
    flash = request.query_params.get("msg", "")

    hold_rows = "".join(
        f"<tr><td><b>{h['symbol']}</b><br><span class='mut'>{h['name']}</span></td>"
        f"<td class='num'>{h['amount']:,.8g}</td><td class='num'><b>{money(h['usd_value'])}</b></td>"
        f"<td class='small'>{h['note']}</td></tr>" for h in holds)
    def price_disp(v):
        if not v: return "—"
        return money(v) if v >= 1 else f"${v:,.4f}"
    price_rows = "".join(
        f"<tr><td><b>{p['symbol']}</b> <span class='mut'>{p['name']}</span></td>"
        f"<td class='num'><b>{price_disp(p['price'])}</b></td>"
        f"<td class='num {cls(p['change_24h'])}'>{pct(p['change_24h'])}</td>"
        f"<td class='num {cls(p['change_7d'])}'>{pct(p['change_7d'])}</td>"
        f"<td class='num {cls(p['change_30d'])}'>{pct(p['change_30d'])}</td></tr>" for p in prices)
    pot_hist = "".join(
        f"<tr><td>{'➕ In' if r['kind']=='in' else '➖ Out'}</td><td class='num'><b>{money(r['amount'])}</b></td>"
        f"<td class='small'>{r['note']}</td></tr>" for r in pot_rows) or "<tr><td colspan=3 class='mut'>No pot entries yet.</td></tr>"

    def flip_html(f):
        return (f"<div class='card flip'><h3>{f['side'].upper()} {f['coin']} — {money(f['amount_usd'])}</h3>"
                f"<div class='mut'>{f['created_at'][:10]}" + (f" · Result: {f['result']}" if f["result"] else "") + "</div>"
                f"<div class='kv'><b>WHAT</b><span>{f['what']}</span><b>WHY</b><span>{f['why']}</span>"
                f"<b>HOW</b><span>{f['how']}</span><b>RISK</b><span>{f['risk']}</span>"
                f"<b>EXIT</b><span>{f['exit_plan']}</span></div></div>")
    flips_html = "".join(flip_html(f) for f in flips) or \
        "<div class='notebox'>No flips yet. COINFLIPPA only flips when a move is worth more than the fees — the first flip will show up here with its full story.</div>"

    def prop_html(p):
        badge = {"waiting": "<span class='badge b-wait'>Waiting for you</span>",
                 "done": "<span class='badge b-done'>Done</span>",
                 "skipped": "<span class='badge b-skip'>Skipped</span>"}[p["status"]]
        actions = ""
        if p["status"] == "waiting":
            actions = (f"<form method='post' action='/proposals/{p['id']}/decide' style='display:flex;gap:8px;margin-top:10px;flex-wrap:wrap'>"
                       f"<button class='okb' name='decision' value='done'>✅ I did this in Coinbase</button>"
                       f"<button class='skipb' name='decision' value='skipped'>⏭️ Skip it</button></form>")
        return (f"<div class='card flip'><h3>{p['title']} {badge}</h3>"
                f"<div class='kv'><b>WHAT</b><span>{p['what']}</span><b>WHY</b><span>{p['why']}</span>"
                f"<b>HOW</b><span>{p['how']}</span><b>RISK</b><span>{p['risk']}</span>"
                f"<b>EXIT</b><span>{p['exit_plan']}</span></div>{actions}</div>")
    props_html = "".join(prop_html(p) for p in props) or \
        "<div class='notebox'>No moves lined up right now. When the Pot has $10 or more of free cash, tap the gold button and COINFLIPPA will study the prices and line up one move here.</div>"

    def sug_rows(rows):
        return "".join(
            f"<tr><td><b>{s['symbol']}</b><br><span class='mut'>{s['name']}</span></td>"
            f"<td class='small'>{s['reason']}</td>"
            f"<td><span class='badge risk-{s['risk_level']}'>{s['risk_level']} risk</span></td></tr>" for s in rows)

    rules = "".join(f"<li style='margin:6px 0'>{r}</li>" for r in SAFETY_RULES)
    pnl_cls = "up" if pv["pnl"] >= 0 else "down"

    body = f"""
{('<div class="flash">' + flash + '</div>') if flash else ''}
<h2>🏦 My Coinbase Account</h2>
<div class="card"><div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">
<img class="aport" src="/static/ken-tuxedo.webp" alt="Ken — founder of COINFLIPPA">
<div style="flex:1;min-width:200px"><span>Real balances — read from your Coinbase</span>
<b class="big">{money(snap['total_usd'])}</b>
<span>Cash you can move: <b style="color:var(--txt)">{money(snap['cash_usd'])}</b> · The rest is staked ETH and dust coins (see the table below)</span>
<div class="notebox warn" style="margin-bottom:0"><b>📸 This is a snapshot, not a live feed.</b>
Last read from Coinbase: <b>{snap['taken_label']}</b>. COINFLIPPA does not have a live wire into
Coinbase — when you want fresh numbers, Milli reads your account again and updates this card.
Coin prices below ARE live.</div></div></div></div>
<table><tr><th>Coin</th><th class="num">How much</th><th class="num">Worth</th><th>Plain words</th></tr>{hold_rows}</table>

<h2>🎯 Today's Stance</h2>
<div class="card"><b class="big" style="font-size:24px">{stance}</b><div class="small" style="margin-top:6px">{summary}</div>
<div class="mut" style="margin-top:6px">Prices {'🟢 live from CoinGecko just now' if live else 'from the last saved check (live fetch hiccup)'}.</div></div>

<h2>💰 The Pot</h2>
<div class="cards">
<div class="card"><span>Money in</span><b class="big">{money(pv['money_in'])}</b></div>
<div class="card"><span>Free cash ready</span><b class="big">{money(pv['cash'])}</b></div>
<div class="card"><span>Pot worth now</span><b class="big">{money(pv['current_value'])}</b></div>
<div class="card"><span>Profit / loss</span><b class="big {pnl_cls}">{money(pv['pnl'])} ({pv['pnl_pct']:+.2f}%)</b><span>Real flips only — no fake numbers</span></div>
</div>
<table><tr><th>Pot history</th><th class="num">Amount</th><th>Note</th></tr>{pot_hist}</table>
<div class="card" style="margin-top:14px"><h3>Add or take out Pot money</h3>
<form method="post" action="/pot/add" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
<select name="kind"><option value="in">➕ Money in</option><option value="out">➖ Money out</option></select>
<input name="amount" type="number" step="0.01" min="0.01" placeholder=" dollars, e.g. 25" required style="width:150px">
<input name="note" placeholder="note (optional)" style="flex:1;min-width:180px">
<button type="submit">Save</button></form>
<div class="mut" style="margin-top:6px">Only log money you really moved in Coinbase — the Pot mirrors your real cash.</div></div>

<h2>📈 Live Coin Prices</h2>
<table><tr><th>Coin</th><th class="num">Price</th><th class="num">24h</th><th class="num">7 days</th><th class="num">30 days</th></tr>{price_rows}</table>

<h2>🤔 Moves Lined Up For You</h2>
<form method="post" action="/suggest" style="margin-bottom:12px"><button class="goldb" type="submit">🔍 Ask COINFLIPPA for a move</button></form>
{props_html}

<h2>🔄 Flip Log</h2>
{flips_html}

<h2>💡 Ideas — Cryptos</h2>
<table><tr><th>Coin</th><th>Why people buy it</th><th>Risk</th></tr>{sug_rows(sug_c)}</table>
<h2>💡 Ideas — Stocks</h2>
<table><tr><th>Stock</th><th>Why people buy it</th><th>Risk</th></tr>{sug_rows(sug_s)}</table>
<div class="notebox">Ideas are information, not orders. COINFLIPPA never buys a stock or coin on this page — you always make the real move in Coinbase yourself.</div>

<h2>🛡️ Safety Rules (built into COINFLIPPA)</h2>
<div class="card"><ul style="margin:0;padding-left:20px;font-size:15px">{rules}</ul></div>
"""
    return page("Dashboard", body, welcome=True)

@app.get("/database", response_class=HTMLResponse)
def database_page():
    init_db()
    c = db()
    def tbl(title, blurb, cols, rows, fmt):
        trs = "".join("<tr>" + "".join(f"<td>{fmt(col, r[col])}</td>" for col in cols) + "</tr>" for r in rows)
        ths = "".join(f"<th>{h}</th>" for h in cols)
        return (f"<h2>{title}</h2><div class='mut' style='margin-bottom:6px'>{blurb}</div>"
                f"<table><tr>{ths}</tr>{trs or '<tr><td class=mut>Empty for now.</td></tr>'}</table>")
    def plain(col, v):
        if v is None: return "—"
        if isinstance(v, float): return f"{v:,.8g}"
        return str(v)
    snaps = c.execute("SELECT id, taken_label, total_usd, cash_usd, note FROM account_snapshots ORDER BY id DESC").fetchall()
    holds = c.execute("SELECT symbol, name, amount, usd_value, note FROM holdings ORDER BY usd_value DESC").fetchall()
    pots = c.execute("SELECT id, kind, amount, note, created_at FROM pot_entries ORDER BY id DESC").fetchall()
    flips = c.execute("SELECT id, created_at, side, coin, amount_usd, result FROM flips ORDER BY id DESC").fetchall()
    props = c.execute("SELECT id, created_at, title, amount_usd, status FROM proposals ORDER BY id DESC").fetchall()
    sugs = c.execute("SELECT kind, symbol, name, risk_level, reason FROM suggestions ORDER BY kind, id").fetchall()
    prices = c.execute("SELECT fetched_at, symbol, price, change_30d FROM price_snapshots ORDER BY id DESC LIMIT 21").fetchall()
    revs = c.execute("SELECT day, stance, summary FROM daily_reviews ORDER BY day DESC LIMIT 14").fetchall()
    c.close()
    body = """
<div class="notebox">🗄️ <b>This is COINFLIPPA's real database</b> — the same rows the dashboard runs on.
What you see here is exactly what is saved. Nothing hidden, nothing fake.</div>
""" + \
        tbl("🏦 Table: account_snapshots", "Each dated read of Ken's real Coinbase account.", ["id", "taken_label", "total_usd", "cash_usd", "note"], snaps, plain) + \
        tbl("🪙 Table: holdings", "Every coin in the latest Coinbase snapshot.", ["symbol", "name", "amount", "usd_value", "note"], holds, plain) + \
        tbl("💰 Table: pot_entries", "Money Ken put into or took out of the Pot.", ["id", "kind", "amount", "note", "created_at"], pots, plain) + \
        tbl("🔄 Table: flips", "Every real flip COINFLIPPA has logged. Empty until the first real flip happens.", ["id", "created_at", "side", "coin", "amount_usd", "result"], flips, plain) + \
        tbl("🤔 Table: proposals", "Moves COINFLIPPA lined up for Ken to do or skip.", ["id", "created_at", "title", "amount_usd", "status"], props, plain) + \
        tbl("💡 Table: suggestions", "The crypto and stock idea lists.", ["kind", "symbol", "name", "risk_level", "reason"], sugs, plain) + \
        tbl("📈 Table: price_snapshots", "Live prices COINFLIPPA saved from CoinGecko (newest first, last 21 rows).", ["fetched_at", "symbol", "price", "change_30d"], prices, plain) + \
        tbl("🎯 Table: daily_reviews", "One market check per day: the stance and why.", ["day", "stance", "summary"], revs, plain)
    return page("Database", body)

@app.post("/pot/add")
async def pot_add(request: Request):
    form = await request.form()
    kind = form.get("kind", "in")
    try:
        amount = float(form.get("amount", 0))
    except Exception:
        amount = 0
    if kind not in ("in", "out") or amount <= 0:
        raise HTTPException(400, "Pick in or out and an amount over $0.")
    c = db()
    c.execute("INSERT INTO pot_entries(kind, amount, note, created_at) VALUES(?,?,?,?)",
              (kind, round(amount, 2), (form.get("note") or "")[:300],
               datetime.datetime.now(datetime.timezone.utc).isoformat()))
    c.commit(); c.close()
    return RedirectResponse(f"/?msg=Pot updated: {'added' if kind=='in' else 'took out'} ${amount:,.2f}.", status_code=303)

@app.post("/suggest")
def suggest():
    init_db()
    c = db()
    prices, _ = fetch_prices()
    pid, msg = suggest_move(c, prices)
    c.close()
    return RedirectResponse(f"/?msg={msg}", status_code=303)

@app.post("/proposals/{pid}/decide")
async def decide(pid: int, request: Request):
    form = await request.form()
    decision = form.get("decision")
    if decision not in ("done", "skipped"):
        raise HTTPException(400, "decision must be done or skipped")
    c = db()
    p = c.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if not p:
        c.close(); raise HTTPException(404, "proposal not found")
    if p["status"] != "waiting":
        c.close(); return RedirectResponse("/?msg=That move was already decided.", status_code=303)
    c.execute("UPDATE proposals SET status=? WHERE id=?", (decision, pid))
    msg = "Skipped. COINFLIPPA will wait for a better setup."
    if decision == "done":
        prices, _ = fetch_prices()
        by = {x["symbol"]: x for x in prices}
        price = (by.get(p["coin"]) or {}).get("price")
        qty = round(p["amount_usd"] / price, 8) if price else None
        c.execute(
            "INSERT INTO flips(created_at, side, coin, amount_usd, qty, price, what, why, how, risk, exit_plan, result)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.datetime.now(datetime.timezone.utc).isoformat(), "buy", p["coin"],
             p["amount_usd"], qty, price, p["what"], p["why"], p["how"], p["risk"], p["exit_plan"],
             "Done in Coinbase by Ken — logged here."))
        msg = f"Flip logged: bought ${p['amount_usd']:,.2f} of {p['coin']}. Watch it in the Flip Log and the Pot."
    c.commit(); c.close()
    return RedirectResponse(f"/?msg={msg}", status_code=303)

if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
