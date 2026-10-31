"""Build the daily rung sheet: what to do now, and the standing orders each position should have."""
import csv, html
from collections import defaultdict
from datetime import date
from .db import connect
from .engine import plan_position
from .prices import latest


def build_plan(db_path="data/trader.db", levels=2, rounding="nearest"):
    con = connect(db_path)
    px = latest(con)
    plans = []
    for p in con.execute("SELECT * FROM positions ORDER BY account, ticker"):
        q = px.get(p["ticker"])
        if not q:
            plans.append(dict(account=p["account"], ticker=p["ticker"], status="no_price", shares=p["shares"], basis=p["basis"]))
            continue
        plan = plan_position(p["shares"], p["basis"], p["band"], q["close"], levels, rounding)
        if p["style"] == "hold":
            plan.update(status="hold", act_now=None, sells=[], buys=[])
        elif plan["status"] == "review":
            plan["note"] = f"Value is {plan['value'] / p['basis']:.0%} of basis — basis may need setting"
        plan.setdefault("note", p["note"])
        plan.update(account=p["account"], ticker=p["ticker"], price_date=q["date"], price_source=q["source"])
        plans.append(plan)
    return plans


def _money(x):
    return f"${x:,.2f}" if abs(x) < 1000 else f"${x:,.0f}"


def _px(x):
    return f"${x:,.2f}"


def _rung(r):
    return f'<span class="q">{r["side"].title()} {r["shares"]:,}</span> @ {_px(r["limit"])}' if r else "—"


def write_html(plans, path, as_of=None, rounding="nearest"):
    as_of = as_of or date.today().isoformat()
    act = [p for p in plans if p.get("status") == "act_now"]
    review = [p for p in plans if p.get("status") in ("review", "no_price", "hold")]
    live = [p for p in plans if p.get("status") in ("ok", "act_now")]
    sources = sorted({(p.get("price_source"), p.get("price_date")) for p in live})
    by_acct = defaultdict(list)
    for p in live:
        by_acct[p["account"]].append(p)

    rows_act = "".join(
        f'<tr><td>{html.escape(p["account"])}</td><td class="t">{p["ticker"]}</td>'
        f'<td class="{ "sell" if p["act_now"]["side"]=="SELL" else "buy"}">{p["act_now"]["side"].title()} {p["act_now"]["shares"]:,}</td>'
        f'<td>{_px(p["act_now"]["limit"])}</td><td>{_money(p["value"])}</td><td>{_money(p["basis"])}</td>'
        f'<td class="{ "pos" if p["drift"]>0 else "neg"}">{p["drift"]:+,.0f}</td></tr>' for p in act)

    acct_sections = ""
    for acct, ps in sorted(by_acct.items()):
        ps = sorted(ps, key=lambda p: -abs(p["drift"]) / p["basis"])
        body = ""
        for p in ps:
            s = p["sells"] + [None] * (2 - len(p["sells"]))
            b = p["buys"] + [None] * (2 - len(p["buys"]))
            flag = ' <span class="tag">act now</span>' if p["status"] == "act_now" else ""
            body += (f'<tr><td class="t">{p["ticker"]}{flag}</td><td>{p["shares"]:,}</td><td>{_px(p["price"])}</td>'
                     f'<td>{_money(p["value"])}</td><td>{_money(p["basis"])}</td>'
                     f'<td class="{ "pos" if p["drift"]>0 else "neg"}">{p["drift"]:+,.0f}</td>'
                     f'<td class="sell">{_rung(s[0])}</td><td class="buy">{_rung(b[0])}</td>'
                     f'<td class="sell dim">{_rung(s[1])}</td><td class="buy dim">{_rung(b[1])}</td></tr>')
        acct_sections += f"""
        <h2>{html.escape(acct)} <span class="count">{len(ps)} positions</span></h2>
        <div class="scroll"><table>
          <thead><tr><th>Ticker</th><th>Shares</th><th>Price</th><th>Value</th><th>Basis</th><th>Drift</th>
          <th>Sell order</th><th>Buy order</th><th>Next sell</th><th>Next buy</th></tr></thead>
          <tbody>{body}</tbody></table></div>"""

    rows_review = "".join(
        f'<tr><td>{html.escape(p["account"])}</td><td class="t">{p["ticker"]}</td><td>{p["shares"]:,}</td>'
        f'<td>{_money(p.get("value", 0)) if p.get("value") else "—"}</td><td>{_money(p["basis"])}</td>'
        f'<td>{"No price" if p["status"]=="no_price" else html.escape(p.get("note") or "")}</td></tr>'
        for p in review)

    src = ", ".join(f"{s} ({d})" for s, d in sources)
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Rung Sheet {as_of}</title>
<style>
:root {{ --bg:#fbfaf7; --ink:#1d1d1b; --muted:#6b6a65; --rule:#e4e2dc; --sell:#a1361f; --buy:#1f6b3a; --tag:#b7791f; --card:#fff; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161614; --ink:#ecebe6; --muted:#9b9a94; --rule:#2e2d2a; --sell:#f08a6c; --buy:#7fcf98; --tag:#e9b45c; --card:#1e1e1b; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:28px 16px 64px }}
h1 {{ font-size:28px; margin:0 0 4px }} h2 {{ font-size:20px; margin:36px 0 10px }}
.sub {{ color:var(--muted); margin:0 0 24px }} .count {{ color:var(--muted); font-weight:400; font-size:15px }}
.scroll {{ overflow-x:auto; background:var(--card); border:1px solid var(--rule); border-radius:10px }}
table {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums }}
th {{ text-align:left; font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); font-weight:600; padding:10px 12px; border-bottom:1px solid var(--rule); white-space:nowrap }}
td {{ padding:10px 12px; border-bottom:1px solid var(--rule); white-space:nowrap }}
tr:last-child td {{ border-bottom:0 }}
.t {{ font-weight:700 }} .sell {{ color:var(--sell) }} .buy {{ color:var(--buy) }} .dim {{ opacity:.6 }}
.q {{ font-weight:600 }} .pos {{ color:var(--sell) }} .neg {{ color:var(--buy) }}
.tag {{ font-size:11px; font-weight:700; color:var(--tag); border:1px solid var(--tag); border-radius:4px; padding:1px 5px; margin-left:6px; vertical-align:2px }}
.note {{ color:var(--muted); font-size:14px; margin-top:28px; max-width:760px }}
.empty {{ color:var(--muted); padding:14px 12px }}
@media print {{ body {{ background:#fff }} .scroll {{ border:0 }} }}
</style></head><body><main>
<h1>Rung Sheet — {as_of}</h1>
<p class="sub">Standing GTC limit orders for each position. Prices: {html.escape(src) or "none"}. Rounding: {rounding}.</p>

<h2>Act now <span class="count">{len(act)} positions already outside their band</span></h2>
<div class="scroll"><table><thead><tr><th>Account</th><th>Ticker</th><th>Trade</th><th>Limit</th><th>Value</th><th>Basis</th><th>Drift</th></tr></thead>
<tbody>{rows_act or '<tr><td colspan="7" class="empty">Nothing to do right now.</td></tr>'}</tbody></table></div>
{acct_sections}

<h2>Needs review <span class="count">{len(review)}</span></h2>
<div class="scroll"><table><thead><tr><th>Account</th><th>Ticker</th><th>Shares</th><th>Value</th><th>Basis</th><th>Why</th></tr></thead>
<tbody>{rows_review or '<tr><td colspan="6" class="empty">None.</td></tr>'}</tbody></table></div>

<p class="note">How to read this: keep the <b>Sell order</b> and <b>Buy order</b> resting at the broker as good-til-cancelled limit orders.
When either one fills, the other is stale — regenerate this sheet and replace both. "Next sell / next buy" are the rungs behind them,
shown so you can see how the ladder continues. For rows tagged <b>act now</b>, the standing orders assume the act-now trade
has already filled. Drift is today's value minus basis. Basis and band per position: $2,500 ±$200,
$5,000 ±$200, $10,000 ±$400; whole shares only.</p>
</main></body></html>"""
    with open(path, "w") as f:
        f.write(doc)


def write_orders_csv(plans, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["account", "ticker", "action", "side", "shares", "limit", "position_after", "value_after"])
        for p in plans:
            if p.get("act_now"):
                a = p["act_now"]
                w.writerow([p["account"], p["ticker"], "act_now", a["side"], a["shares"], a["limit"], "", ""])
            for r in p.get("sells", [])[:1] + p.get("buys", [])[:1]:
                w.writerow([p["account"], p["ticker"], "standing_gtc", r["side"], r["shares"], r["limit"], r["after_shares"], r["after_value"]])
