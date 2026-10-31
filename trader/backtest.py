"""Replay every trade in the ledger and ask: would the engine have made this trade?

For each historical trade, using the position as it stood just before it:
  side_ok  — engine would have traded the same direction at that price
  exact    — and the same number of shares
  close    — within 25% of his share count (or 1 share)
  inside   — position was still inside the band, so the engine would not have traded at all
"""
from collections import defaultdict
from .db import connect, TIERS
from .engine import size_trade
from .history import trades_from_lots, nearest_tier


def replay_position(trades, rounding="nearest", window=5, band_override=None):
    held, post, rows = 0, [], []
    for i, (d, side, n, px) in enumerate(trades):
        mv = held * px
        after = held + (n if side == "BUY" else -n)
        w = sorted((post + [after * px])[-window:])
        B = nearest_tier(w[len(w) // 2])                      # rolling basis, follows tier changes
        band = band_override or TIERS[B]
        post.append(after * px)
        if held == 0:
            pred, pn, why = "BUY", None, "open"
        elif mv >= B + band:
            pred, why = "SELL", "upper"; pn = size_trade(held, px, B, "SELL", rounding)
        elif mv <= B - band:
            pred, why = "BUY", "lower"; pn = size_trade(held, px, B, "BUY", rounding)
        else:
            pred, pn, why = None, 0, "inside"
        rows.append(dict(date=d, side=side, shares=n, price=round(px, 2), value_before=round(mv), basis=B,
                         predicted=pred, predicted_shares=pn, why=why,
                         side_ok=pred == side, exact=pred == side and pn == n,
                         close=pred == side and pn is not None and abs(pn - n) <= max(1, 0.25 * n)))
        held = after
    return rows


def run(db_path="data/trader.db", rounding="nearest", band_override=None):
    con = connect(db_path)
    lots = defaultdict(list)
    for r in con.execute("SELECT * FROM lots ORDER BY buy_date"):
        lots[(r["account"], r["ticker"])].append(dict(shares=r["shares"], cost_ps=r["cost_ps"], buy_date=r["buy_date"],
                                                       sell_px=r["sell_px"], sell_date=r["sell_date"]))
    results = {}
    for key, ls in lots.items():
        rows = [x for x in replay_position(trades_from_lots(ls), rounding, band_override=band_override) if x["why"] != "open"]
        if rows:
            results[key] = rows
    return results


def summarize(results):
    def pct(rows, k):
        return round(100 * sum(r[k] for r in rows) / len(rows)) if rows else 0
    allrows = [r for rows in results.values() for r in rows]
    per = {f"{t} ({a})": dict(trades=len(rows), side=pct(rows, "side_ok"), exact=pct(rows, "exact"), close=pct(rows, "close"),
                             inside=sum(r["why"] == "inside" for r in rows))
           for (a, t), rows in sorted(results.items(), key=lambda kv: kv[0][1])}
    total = dict(trades=len(allrows), side=pct(allrows, "side_ok"), exact=pct(allrows, "exact"), close=pct(allrows, "close"),
                 inside=sum(r["why"] == "inside" for r in allrows),
                 buy_exact=pct([r for r in allrows if r["side"] == "BUY"], "exact"),
                 sell_exact=pct([r for r in allrows if r["side"] == "SELL"], "exact"))
    return per, total
