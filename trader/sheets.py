"""Parse Dad's per-stock Google Sheets (CSV exports) into normalized tables.

Sheet layout (one per ticker):
  rows 1-2   : two-line column headers
  row 3      : account name (e.g. "Randol IRA")      -> may repeat for a 2nd account block
  lot rows   : shares, cost/share, sell price, buy date, sell date, cost, proceeds, mv, realized, unrealized
  totals row : shares with no cost/share and no dates
  footer     : "52 week high", "Stock Grader", "Zacks Rank", "<newsletter> <date> <price>", "Buy below"
"""
import csv, glob, os, re, sys
from datetime import datetime

NUM = lambda s: float(s.replace(",", "").replace("(", "-").replace(")", "")) if s and s.strip() not in ("", "–") else None

def normalize_account(name):
    """Dad spells the same account more than one way ("Randol Fidelity Brokerage" / "Randol Fidelity Account")."""
    n = " ".join(name.split())
    if re.search(r"fidelity", n, re.I):
        return "Randol Fidelity"
    return n


def parse_date(s):
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except Exception:
            pass
    return None

def parse_sheet(path):
    ticker = os.path.splitext(os.path.basename(path))[0]
    rows = list(csv.reader(open(path, newline="")))
    rows = [r + [""] * (12 - len(r)) for r in rows]
    account = None
    lots, meta, blocks = [], {"ticker": ticker, "newsletters": []}, []
    current_price = None
    for r in rows[2:]:
        a, b, shares, cps, sold_px, buy_d, sell_d, cost, proceeds, mv, realized, unreal = r[:12]
        # account header — usually on its own row, but sometimes on the same row as the account's first lot
        if b and re.search(r"IRA|Roth|Brokerage|Account|Fidelity", b, re.I):
            account = normalize_account(b)
            if not shares:
                continue
        if a and current_price is None and b and b.strip() == ticker:
            current_price = NUM(a)
        bd = parse_date(buy_d)
        is_num = bool(re.fullmatch(r"[\d,]+", shares.strip()))
        if is_num and bd and NUM(cps):  # lot row
            lots.append(dict(ticker=ticker, account=account, shares=int(NUM(shares)), cost_ps=NUM(cps),
                             sell_px=NUM(sold_px), buy_date=bd, sell_date=parse_date(sell_d),
                             cost=NUM(cost), proceeds=NUM(proceeds), mv=NUM(mv),
                             realized=NUM(realized), unrealized=NUM(unreal)))
            continue
        if is_num and not cps and not bd and cost:  # totals row
            blocks.append(dict(account=account, shares=int(NUM(shares)), cost=NUM(cost), proceeds=NUM(proceeds),
                               mv=NUM(mv), realized=NUM(realized), unrealized=NUM(unreal)))
            continue
        # footer
        key = (b or "").strip().lower()
        if "52 week high" in key: meta["high_52w"] = NUM(a)
        elif "target" in key: meta["target_1y"] = NUM(a)
        elif "grader" in key: meta["grade"] = shares.strip()
        elif "zacks" in key: meta["zacks"] = shares.strip()
        elif key.startswith("buy below"): meta.setdefault("buy_below", []).append(NUM(shares))
        elif "recent" in key or "52 week" in key: meta.setdefault("ref", {})[key] = NUM(a)
        elif b and not bd:
            cells = r[2:8]
            for i, c in enumerate(cells):
                if parse_date(c):
                    bucket = cells[0].strip() if i > 0 and cells[0].strip() else None
                    meta["newsletters"].append(dict(name=b.strip(), bucket=bucket, date=parse_date(c),
                                                    price=NUM(cells[i + 1]) if i + 1 < len(cells) else None))
                    break
    meta["current_price"] = current_price
    meta["accounts"] = sorted({l["account"] for l in lots if l["account"]})
    return dict(meta=meta, lots=lots, blocks=blocks)

if __name__ == "__main__":
    for p in sorted(glob.glob(sys.argv[1] if len(sys.argv) > 1 else "sheets/*.csv")):
        s = parse_sheet(p)
        m = s["meta"]
        open_sh = sum(l["shares"] for l in s["lots"] if not l["sell_date"])
        print(f"{m['ticker']:6} px={m.get('current_price')} accts={m['accounts']} lots={len(s['lots'])} open_sh={open_sh} "
              f"grade={m.get('grade')} zacks={m.get('zacks')} buybelow={m.get('buy_below')} nl={[n['name'] for n in m['newsletters']]}")
