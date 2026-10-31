# dad-trader

Automates Dad's constant-value trading system. Today it does one job: turn his per-stock Google Sheets
into a **daily rung sheet** — the standing buy and sell limit orders each position should have resting at
the broker. Nothing here places trades.

## The system, as confirmed with Dad (Oct 30, 2026)

- Each position has a constant-dollar **basis**: $2,500, $5,000 or $10,000.
- **Band** on market value (shares × price): ±$200, ±$200, ±$400.
- Above basis + band → sell; below basis − band → buy; **whole shares only**, enough to return to basis.
- Basis stays put after a trade. Trades fire intraday via standing GTC limit orders.
- Picks come from four InvestorPlace services (Growth Investor, Early Stage Investor, Fry's Investment Report,
  Innovation Investor); Dad adds and removes names weekly. Freed cash is redeployed.

## Quick start

```bash
pip install -r requirements.txt           # stdlib only, plus pytest; yfinance optional
# export each stock's Google Sheet as CSV into data/sheets/<TICKER>.csv
python -m trader seed                     # build data/trader.db from the sheets
python -m trader prices --yahoo           # live closes (needs internet + yfinance), or:
python -m trader prices --csv quotes.csv  #   a ticker,price file you maintain
python -m trader rungs                    # -> out/rung-sheet-<date>.html, out/orders-<date>.csv
python -m trader backtest                 # -> out/backtest.md
python -m pytest -q
```

Without a `prices` step, the rung sheet uses the "Current Price" cell from each sheet export.

## Deploy to the EC2 server (RHEL 8/9)

```bash
scp -i KEY.pem dad-trader.zip ec2-user@trader.wellslabs.dev:~     # from your Mac
ssh -i KEY.pem ec2-user@trader.wellslabs.dev
unzip -oq dad-trader.zip && cd dad-trader && bash deploy/install.sh --https you@example.com
```

`deploy/install.sh` finds nginx or httpd, installs Python 3.11, copies the app to `/opt/dad-trader`, seeds the
database, publishes the rung sheet as the site's `index.html`, asks for passwords for users `dad` and `jeff`,
schedules refreshes (weekdays 8:30, 12:00, 3:15 Central), and with `--https` gets a Let's Encrypt certificate.
Re-run it after updating the zip; it keeps the passwords. Refresh by hand: `/opt/dad-trader/publish.sh`.

## Layout

| File | What it does |
|---|---|
| `trader/sheets.py` | Parses Dad's sheet layout: lots, account blocks, totals rows, footer metadata (grade, Zacks, newsletters, Buy Below) |
| `trader/db.py` | SQLite schema. Positions keyed on **(account, ticker)** — he holds some tickers in two accounts |
| `trader/history.py` | Lots → trades; infers each position's basis from where it settles after trades |
| `trader/seed.py` | Loads the sheets; classifies each position as `system` (laddered) or `hold` (listed for review) |
| `trader/engine.py` | The rule: trade sizing, rung prices, act-now detection |
| `trader/backtest.py` | Replays every historical trade and scores the engine against what Dad did |
| `trader/report.py` | Rung sheet HTML + orders CSV |
| `trader/prices.py` | Price sources: sheet snapshot, CSV, Yahoo |

## What the pilot found (25 sheets, 1,864 trades)

- Three accounts: Randol IRA, June IRA, Randol Fidelity. AGX, CLS, CRS, PANW, RDW, AUR are held in two.
- **Not everything is the system.** Randol IRA bought AGX, CRS and RDW as single blocks on Aug 20, 2026
  (all tagged *A/I Revolution Portfolio*) and hasn't rebalanced them. Those, and stale Fidelity lots, are
  classified `hold` and get no rungs.
- Engine vs history: same direction 70%, exact share count 36%, within 25% of his size 61%.
  Buys on $100+ stocks match best (70–80% exact on GOOGL, CLS, PANW, CRS).
- `nearest` rounding matches his trades slightly better than `above` (36% vs 35% exact; sells 36% vs 33%).
  Default is `nearest`; `--rounding above` is available.
- He trades inside the ±$200 band about 29% of the time and often lets drift run to $300+. The rule is
  enforced as stated; tuning rung spacing per position is the next step.

## Open questions for Dad

1. Cheap stocks (ACHR, ENVX, AUR): how does he pick the share count when selling into a bounce?
2. Where does he place standing orders — how far from basis, how many at once?
3. Are *Green Zone Fortunes* and *A/I Revolution Portfolio* active sources? Is the A/I block a separate strategy?
4. Is the Randol Fidelity account part of the system at all?

## Not built yet

Newsletter ingest (portfolio-page diff + alert parsing), tier-up/down recommendations, weekly add/drop review,
fill entry / reconciliation, broker execution.

Dad's sheet exports, the database and generated output are financial data and are git-ignored.
