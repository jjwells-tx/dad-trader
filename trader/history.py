"""Turn lot rows into a trade history and infer each position's basis from it."""
from collections import defaultdict
from .db import TIERS


def trades_from_lots(lots):
    """Aggregate lots into trades (date, side, shares, avg_price).

    Several lots bought or sold on the same day are treated as one order. On a day with
    both, buys come first: he buys the dip, then sells into the rebound.
    """
    agg = defaultdict(lambda: [0, 0.0])
    for l in lots:
        k = (l["buy_date"], "BUY")
        agg[k][0] += l["shares"]
        agg[k][1] += l["shares"] * l["cost_ps"]
        if l["sell_date"] and l["sell_px"]:
            k = (l["sell_date"], "SELL")
            agg[k][0] += l["shares"]
            agg[k][1] += l["shares"] * l["sell_px"]
    out = [(d, side, n, v / n) for (d, side), (n, v) in agg.items() if n]
    return sorted(out, key=lambda t: (t[0], 0 if t[1] == "BUY" else 1))


def nearest_tier(value):
    return min(TIERS, key=lambda t: abs(t - value))


def infer_basis(trades, window=5):
    """Tier nearest the median post-trade market value of the last `window` trades.

    He trades back to basis, so post-trade value tracks the tier — and a rolling window
    follows tier changes (STX moved $2.5k → $5k, ACHR/AUR $5k → $10k and back).
    """
    held, post = 0, []
    for _, side, n, px in trades:
        held += n if side == "BUY" else -n
        if held > 0:
            post.append(held * px)
    if not post:
        return 5000
    w = sorted(post[-window:])
    return nearest_tier(w[len(w) // 2])


def by_account(lots):
    out = defaultdict(list)
    for l in lots:
        out[l["account"] or "Unknown"].append(l)
    return out
