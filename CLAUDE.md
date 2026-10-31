# dad-trader — notes for Claude

Jeff is automating his dad's constant-value stock trading system. The app turns Dad's per-stock Google Sheets
into a daily **rung sheet**: the standing GTC limit orders each position should have resting at Wells Fargo
(WellsTrade). It never places trades — WellsTrade has no API, and Dad enters orders himself.

## The rule (confirmed with Dad, Oct 30 2026)

- Each position has a constant-dollar basis: $2,500 / $5,000 / $10,000, with a band of ±$200 / ±$200 / ±$400.
- Band is on **market value** (shares × price), not on cost.
- At basis + band, sell; at basis − band, buy. **Whole shares only**, enough to return to basis. Basis never
  resets after a trade; only a tier change moves it.
- Trades fire intraday through standing limit orders. When one fills, recompute both rungs for that position.
- Rounding: `nearest` is the default because it reproduces his history best (his Oct 29 2026 GOOGL buy of 3
  shares is a nearest-rounding trade). Dad *said* "above"; `--rounding above` exists. Don't flip the default
  without backtest evidence.

## Things that are easy to get wrong

- Positions are keyed on **(account, ticker)**. Accounts: Randol IRA, June IRA, Randol Fidelity. Several
  tickers are held in two accounts with different bases.
- Not every position is the system. Single block buys with no rebalancing since (Randol IRA AGX/CRS/RDW,
  Aug 20 2026, "A/I Revolution Portfolio") and stale lots are `style='hold'` and get no rungs.
- The share total on Dad's sheets sometimes includes shares already sold. Trust lot rows and market value.
- Sheet layout quirks live in `trader/sheets.py`: account labels can share a row with the first lot, footer rows
  can contain stray dates, Fidelity is spelled two ways. FXVLT is an annuity tracker, not a stock.
- Data in `data/sheets/`, `data/*.db` and `out/` is Dad's financial data. It is git-ignored; keep it that way.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt yfinance
python -m trader seed          # data/sheets/*.csv -> data/trader.db
python -m trader prices --yahoo
python -m trader rungs         # out/rung-sheet-<date>.html, out/orders-<date>.csv
python -m trader backtest      # out/backtest.md
python -m pytest -q            # engine tests are pinned to real GOOGL trades; keep them passing
```

## Production

https://trader.wellslabs.dev on an EC2 RHEL instance running httpd, behind basic auth (users dad, jeff) and
Let's Encrypt. App lives in `/opt/dad-trader`; cron runs `publish.sh` weekdays at 8:30, 12:00 and 15:15
Central. `deploy/install.sh` sets all of this up and is safe to re-run.

## Open questions for Dad

1. Cheap stocks (ACHR, ENVX, AUR): how does he pick share counts when selling into a bounce? He oversells
   20–30% versus the rule.
2. Where does he place standing orders: how far from basis, how many rungs at once? About 29% of his trades
   happen inside the ±$200 band.
3. Are Green Zone Fortunes and A/I Revolution Portfolio active sources?
4. Is the Randol Fidelity account part of the system?

## Roadmap

1. Read Dad's Google Sheets directly (service account) instead of CSV exports, so positions stay current.
2. Newsletter ingest: diff the four InvestorPlace portfolio pages (Growth Investor, Early Stage Investor,
   Fry's Investment Report, Innovation Investor) and parse alert posts into new/hold/sell signals.
3. Tier up/down recommendations; weekly add/drop review.
4. Fill entry and reconciliation; tune rung spacing per position against history.
