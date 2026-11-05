"""AI chat about Dad's positions, backed by the Gemini API with Google Search grounding.

The model gets a snapshot of the ledger as context (positions, today's rungs, grades, newsletters) and can
search the web for news and prices. The API key stays on the server; the page only talks to /chat.

  GEMINI_API_KEY   required — from https://aistudio.google.com/apikey
  GEMINI_MODEL     optional — defaults to the gemini-flash-latest alias
"""
import json, os, urllib.error, urllib.request
from datetime import date
from .db import connect
from .report import build_plan, positions_info

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-latest"
MAX_TURNS = 20          # messages of history sent to the model
MAX_CHARS = 2000        # per user message


class ChatError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status       # HTTP status for /chat: 400 = bad request, 502/503 = upstream or setup problem


RULES = """\
You are the research assistant on Jeff's "rung sheet" app, which supports his dad's constant-value trading
system. You answer questions from Jeff and his dad about their stocks and the app's numbers.

How the system works:
- Each position has a constant-dollar basis ($2,500 / $5,000 / $10,000) and a band (±$200 / ±$200 / ±$400)
  measured on market value (shares × price).
- At basis + band he sells, at basis − band he buys, whole shares only, enough to return to basis. Basis only
  changes when Dad moves a position to another tier.
- The app lists standing GTC limit orders ("rungs") for each position. "Act now" means the position is already
  outside its band at the last price. "Hold" positions (one-off block buys, stale lots) get no rungs.
  "Review" means value is more than 40% away from basis, so the basis probably needs setting.
- Picks come from InvestorPlace newsletters (Growth Investor, Early Stage Investor, Fry's Investment Report,
  Innovation Investor). "Buy Below" is the newsletter's maximum buy price.
- The app never places trades. Dad enters orders himself at Wells Fargo.

How to answer:
- Be brief and concrete; use the numbers below and say what date they are from.
- For news, earnings, analyst views or anything after the snapshot, search the web and say where it came from.
- If the data below doesn't answer it, say so instead of guessing. Never invent positions, prices or trades.
- You're not a licensed advisor. Give information and reasoning, and leave the decisions to Dad. Don't push
  trades outside his system.
"""


def _money(x):
    return f"${x:,.0f}" if x is not None else "?"


def build_context(db_path="data/trader.db"):
    """Plain-text snapshot of the ledger for the system prompt."""
    con = connect(db_path)
    plans = build_plan(db_path)
    stocks = {r["ticker"]: dict(r) for r in con.execute("SELECT * FROM stocks")}
    lines = [f"Today is {date.today().isoformat()}. Positions from: {positions_info(db_path) or 'unknown'}.", "",
             "POSITIONS (account | ticker | shares | last price (date, source) | value | basis±band | drift | status | orders)"]
    for p in plans:
        if p.get("status") == "no_price":
            lines.append(f"{p['account']} | {p['ticker']} | {p['shares']} sh | no price | basis {_money(p['basis'])} | no_price")
            continue
        orders = []
        if p.get("act_now"):
            a = p["act_now"]
            orders.append(f"ACT NOW {a['side']} {a['shares']} @ {a['limit']:.2f}")
        for r in p.get("sells", []) + p.get("buys", []):
            orders.append(f"{r['side']} {r['shares']} @ {r['limit']:.2f} (level {r['level']}, then {r['after_shares']} sh)")
        lines.append(f"{p['account']} | {p['ticker']} | {p['shares']} sh | {p['price']:.2f} ({p['price_date']}, {p['price_source']}) | "
                     f"{_money(p['value'])} | {_money(p['basis'])}±{p['band']:.0f} | {p['drift']:+,.0f} | {p['status']} | "
                     + ("; ".join(orders) or "none") + (f" | note: {p['note']}" if p.get("note") else ""))
    lines += ["", "STOCK DETAILS FROM DAD'S SHEETS (ticker | grade | Zacks | Buy Below | 52w high | 1y target | newsletters)"]
    for t, s in sorted(stocks.items()):
        nl = ", ".join(f"{n['name']}" + (f" ({n['bucket']})" if n.get("bucket") else "") + (f" rec. {n['date']}" if n.get("date") else "")
                       + (f" @ {n['price']}" if n.get("price") else "") for n in json.loads(s["newsletters"] or "[]"))
        lines.append(f"{t} | {s['grade'] or '?'} | {s['zacks'] or '?'} | {s['buy_below'] or '?'} | {s['high_52w'] or '?'} | "
                     f"{s['target_1y'] or '?'} | {nl or '?'}")
    return "\n".join(lines)


def clean_history(messages):
    """Validate the browser's message list: [{role: user|model, text}], ending with the user's question."""
    if not isinstance(messages, list) or not messages:
        raise ChatError("No question asked.", 400)
    out = []
    for m in messages[-MAX_TURNS:]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "model") or not isinstance(m.get("text"), str):
            raise ChatError("Bad message format.", 400)
        text = m["text"].strip()
        if m["role"] == "user" and len(text) > MAX_CHARS:
            raise ChatError(f"Please keep questions under {MAX_CHARS} characters.", 400)
        if text:
            out.append(dict(role=m["role"], text=text))
    while out and out[0]["role"] != "user":       # Gemini wants the conversation to start with the user
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        raise ChatError("No question asked.", 400)
    return out


def ask(messages, context, api_key=None, model=None, post=None):
    """Send the conversation to Gemini. Returns {reply, sources: [{title, uri}]}.

    `post(url, headers, body) -> dict` can be swapped out in tests.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ChatError("The chat isn't set up: GEMINI_API_KEY is missing on the server.", 503)
    model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    body = {
        "system_instruction": {"parts": [{"text": RULES + "\n\n" + context}]},
        "contents": [{"role": m["role"], "parts": [{"text": m["text"]}]} for m in clean_history(messages)],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.3},
    }
    data = (post or _post)(API.format(model=model), {"x-goog-api-key": api_key, "Content-Type": "application/json"}, body)
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no answer")
        raise ChatError(f"Gemini didn't answer ({reason}).")
    c = cands[0]
    text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []) if not p.get("thought")).strip()
    if not text:
        raise ChatError(f"Gemini returned an empty answer ({c.get('finishReason', 'unknown')}).")
    sources, seen = [], set()
    for ch in (c.get("groundingMetadata") or {}).get("groundingChunks", []):
        w = ch.get("web") or {}
        if w.get("uri") and w["uri"] not in seen:
            seen.add(w["uri"])
            sources.append(dict(title=w.get("title") or w["uri"], uri=w["uri"]))
    return dict(reply=text, sources=sources)


def _post(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e)["error"]["message"]
        except Exception:
            msg = e.reason
        if e.code == 429:
            raise ChatError("The Gemini API's rate limit was hit. Wait a minute and try again.", 429)
        raise ChatError(f"Gemini API error {e.code}: {msg}")
    except urllib.error.URLError as e:
        raise ChatError(f"Couldn't reach Gemini: {e.reason}")
