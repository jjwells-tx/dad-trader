"""Command line:

  python -m trader seed [--sheets 'data/sheets/*.csv']     load Dad's sheet exports into the ledger
  python -m trader prices --csv quotes.csv | --yahoo        refresh prices
  python -m trader rungs [--rounding nearest|above]         write out/rung-sheet-<date>.html and out/orders-<date>.csv
  python -m trader backtest [--rounding ...] [--band N]     replay history; write out/backtest.md
"""
import argparse, os
from datetime import date
from . import seed as seed_mod, backtest, report, prices
from .db import connect


def main(argv=None):
    ap = argparse.ArgumentParser(prog="trader")
    ap.add_argument("--db", default="data/trader.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed"); s.add_argument("--sheets", default="data/sheets/*.csv"); s.add_argument("--as-of")
    p = sub.add_parser("prices"); p.add_argument("--csv"); p.add_argument("--yahoo", action="store_true")
    r = sub.add_parser("rungs"); r.add_argument("--rounding", default="nearest", choices=["nearest", "above"]); r.add_argument("--levels", type=int, default=2)
    b = sub.add_parser("backtest"); b.add_argument("--rounding", default="nearest", choices=["nearest", "above"]); b.add_argument("--band", type=float)
    a = ap.parse_args(argv)
    os.makedirs("out", exist_ok=True)

    if a.cmd == "seed":
        loaded, skipped = seed_mod.seed(a.sheets, a.db, a.as_of)
        con = connect(a.db)
        n, accts = con.execute("SELECT COUNT(*), COUNT(DISTINCT account) FROM positions").fetchone()
        print(f"Loaded {len(loaded)} sheets -> {n} positions in {accts} accounts." + (f" Skipped: {', '.join(skipped)}" if skipped else ""))

    elif a.cmd == "prices":
        con = connect(a.db)
        if a.csv:
            q = prices.from_csv(a.csv); prices.store(con, q, "csv")
        elif a.yahoo:
            tickers = [r[0] for r in con.execute("SELECT DISTINCT ticker FROM positions")]
            q = prices.from_yahoo(tickers); prices.store(con, q, "yahoo")
        else:
            ap.error("give --csv FILE or --yahoo")
        print(f"Stored {len(q)} prices.")

    elif a.cmd == "rungs":
        plans = report.build_plan(a.db, a.levels, a.rounding)
        today = date.today().isoformat()
        h, c = f"out/rung-sheet-{today}.html", f"out/orders-{today}.csv"
        report.write_html(plans, h, today, a.rounding)
        report.write_orders_csv(plans, c)
        act = sum(p.get("status") == "act_now" for p in plans)
        rev = sum(p.get("status") in ("review", "no_price", "hold") for p in plans)
        print(f"{len(plans)} positions: {act} act now, {rev} need review. Wrote {h} and {c}")

    elif a.cmd == "backtest":
        per, tot = backtest.summarize(backtest.run(a.db, a.rounding, a.band))
        lines = [f"# Backtest — rounding={a.rounding}" + (f", band={a.band:g}" if a.band else ", band=tier default"), "",
                 f"{tot['trades']} historical trades. Same side {tot['side']}% · exact shares {tot['exact']}% "
                 f"(buys {tot['buy_exact']}%, sells {tot['sell_exact']}%) · within 25% {tot['close']}% · "
                 f"{tot['inside']} trades made while still inside the band.", "",
                 "| Position | Trades | Same side | Exact | Within 25% | Inside band |", "|---|---:|---:|---:|---:|---:|"]
        lines += [f"| {k} | {v['trades']} | {v['side']}% | {v['exact']}% | {v['close']}% | {v['inside']} |" for k, v in per.items()]
        open("out/backtest.md", "w").write("\n".join(lines) + "\n")
        print(lines[2]); print("Wrote out/backtest.md")


if __name__ == "__main__":
    main()
