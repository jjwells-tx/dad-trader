"""Rung engine: the standing limit orders each position should have resting at the broker.

The rule (confirmed with Dad, Oct 30 2026):
  * Every position has a constant-dollar basis (2,500 / 5,000 / 10,000) and a band (200 / 200 / 400).
  * Band is measured on market value = shares x price.
  * When market value reaches basis + band, sell; at basis - band, buy — whole shares only —
    enough to bring the position back to basis.
  * Trades fire intraday, so instead of watching prices the engine computes the exact price
    where each trade triggers and hands those to the broker as GTC limit orders ("rungs").
    When one fills, recompute every rung for that position.

Rounding: "nearest" trades round(gap / price) shares (what reproduces his history best);
"above" trades enough to land at or just above basis (what he described). See backtest.
"""
import math
from dataclasses import dataclass, asdict

REVIEW_RATIO = 0.4   # positions more than 40% away from basis are flagged, not laddered


@dataclass
class Rung:
    side: str          # BUY | SELL
    limit: float       # limit price
    shares: int        # shares to trade when it fills
    after_shares: int  # position size after the fill
    after_value: float # market value right after the fill
    level: int         # 1 = nearest rung, 2 = the one behind it

    def as_dict(self):
        return asdict(self)


def size_trade(shares_held, price, basis, side, rounding="nearest"):
    """Whole shares to trade at `price` to bring the position back toward basis (min 1)."""
    gap = abs(shares_held * price - basis) / price
    if rounding == "above":
        n = math.floor(gap) if side == "SELL" else math.ceil(gap)
    else:
        n = round(gap)
    if side == "SELL":
        n = min(n, shares_held)
    return max(1, n)


def _cents_up(x):
    return math.ceil(round(x * 100, 6)) / 100


def _cents_down(x):
    return math.floor(round(x * 100, 6)) / 100


def ladder(shares, basis, band, levels=2, rounding="nearest"):
    """Next `levels` sell rungs above and buy rungs below, assuming each rung fills in turn."""
    sells, buys = [], []
    s = shares
    for lvl in range(1, levels + 1):
        if s <= 0:
            break
        px = _cents_up((basis + band) / s)                  # first price where mv >= basis + band
        n = size_trade(s, px, basis, "SELL", rounding)
        s -= n
        sells.append(Rung("SELL", px, n, s, round(s * px, 2), lvl))
    s = shares
    for lvl in range(1, levels + 1):
        if s <= 0:
            break
        px = _cents_down((basis - band) / s)                # first price where mv <= basis - band
        if px <= 0:
            break
        n = size_trade(s, px, basis, "BUY", rounding)
        s += n
        buys.append(Rung("BUY", px, n, s, round(s * px, 2), lvl))
    return sells, buys


def plan_position(shares, basis, band, price, levels=2, rounding="nearest"):
    """Everything the rung sheet needs for one position at today's price."""
    mv = shares * price
    out = dict(shares=shares, basis=basis, band=band, price=price, value=round(mv, 2),
               drift=round(mv - basis, 2), status="ok", act_now=None, sells=[], buys=[])
    if shares <= 0:
        out["status"] = "closed"
        return out
    if abs(mv / basis - 1) > REVIEW_RATIO:
        out["status"] = "review"
        return out
    # already outside the band at today's price: trade now, then ladder from the new size
    if mv >= basis + band or mv <= basis - band:
        side = "SELL" if mv >= basis + band else "BUY"
        n = size_trade(shares, price, basis, side, rounding)
        out["act_now"] = dict(side=side, shares=n, limit=round(price, 2))
        shares = shares - n if side == "SELL" else shares + n
        out["status"] = "act_now"
    sells, buys = ladder(shares, basis, band, levels, rounding)
    out["sells"] = [r.as_dict() for r in sells]
    out["buys"] = [r.as_dict() for r in buys]
    return out
