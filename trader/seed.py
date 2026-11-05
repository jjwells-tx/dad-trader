"""Load Dad's per-stock sheet exports (CSV) into the ledger."""
import glob, json
from datetime import date, datetime
from .db import connect, TIERS
from .sheets import parse_sheet
from .history import trades_from_lots, infer_basis, by_account


BLOCK_GRACE_DAYS = 14    # a brand-new system position also starts as one buy; give it two weeks before calling it a hold
STALE_DAYS = 180


def classify(lots, trades, today):
    """'system' positions get rungs; 'hold' positions are listed for review.

    Hold signals seen in the sheets:
      * every open share came from one block buy and nothing has traded since
        (Randol IRA bought AGX, CRS and RDW this way on Aug 20, 2026 — the A/I Revolution Portfolio)
      * no trade in six months (Randol Fidelity LEU, a single 2025 lot)
    """
    open_dates = {l["buy_date"] for l in lots if not l["sell_date"]}
    last = trades[-1][0]
    if len(open_dates) == 1 and last == next(iter(open_dates)) and (today - last).days > BLOCK_GRACE_DAYS:
        return "hold", f"One block buy on {last.isoformat()} and no rebalancing since — looks buy-and-hold"
    if (today - last).days > STALE_DAYS:
        return "hold", f"No trades since {last.isoformat()}"
    return "system", None


def seed(sheet_glob="data/sheets/*.csv", db_path="data/trader.db", as_of=None, source="CSV export"):
    as_of = as_of or date.today().isoformat()
    con = connect(db_path)
    for t in ("stocks", "positions", "basis_changes", "lots", "prices"):
        con.execute(f"DELETE FROM {t}")
    loaded, skipped = [], []
    for path in sorted(glob.glob(sheet_glob)):
        s = parse_sheet(path)
        m, lots = s["meta"], s["lots"]
        if not lots:
            skipped.append(m["ticker"])          # e.g. FXVLT: annuity tracker, not a trading sheet
            continue
        bb = [x for x in (m.get("buy_below") or []) if x]
        con.execute("INSERT INTO stocks (ticker, grade, zacks, buy_below, newsletters, high_52w, target_1y) VALUES (?,?,?,?,?,?,?)",
                    (m["ticker"], m.get("grade") or None, m.get("zacks") or None, min(bb) if bb else None,
                     json.dumps(m["newsletters"], default=str), m.get("high_52w"), m.get("target_1y")))
        for l in lots:
            con.execute("INSERT INTO lots (account, ticker, shares, cost_ps, buy_date, sell_px, sell_date) VALUES (?,?,?,?,?,?,?)",
                        (l["account"] or "Unknown", m["ticker"], l["shares"], l["cost_ps"], l["buy_date"].isoformat(),
                         l["sell_px"], l["sell_date"].isoformat() if l["sell_date"] else None))
        for acct, al in by_account(lots).items():
            held = sum(l["shares"] for l in al if not l["sell_date"])
            if held <= 0:
                continue
            trades = trades_from_lots(al)
            basis = infer_basis(trades)
            style, note = classify(al, trades, date.fromisoformat(as_of))
            con.execute("INSERT INTO positions (account, ticker, shares, basis, band, style, note, last_trade) VALUES (?,?,?,?,?,?,?,?)",
                        (acct, m["ticker"], held, basis, TIERS[basis], style, note, trades[-1][0].isoformat()))
            con.execute("INSERT INTO basis_changes VALUES (?,?,?,?,?)", (acct, m["ticker"], basis, as_of, "seed"))
        if m.get("current_price"):
            con.execute("INSERT OR REPLACE INTO prices VALUES (?,?,?,?)", (m["ticker"], as_of, m["current_price"], "sheet"))
        loaded.append(m["ticker"])
    con.execute("INSERT OR REPLACE INTO meta VALUES ('positions_source', ?)", (source,))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('positions_loaded', ?)", (datetime.now().strftime("%Y-%m-%d %H:%M"),))
    con.commit()
    return loaded, skipped
