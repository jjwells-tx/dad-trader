"""Price sources. Each returns {ticker: (date, close)} and the result is stored in the `prices` table.

  sheet    — the "Current Price" cell from each sheet export (whatever the sheet showed when exported)
  csv      — a two-column file you maintain: ticker,price
  yahoo    — live quotes via the yfinance package (pip install yfinance); needs internet access
"""
import csv
from datetime import date


def from_csv(path):
    today = date.today().isoformat()
    out = {}
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].strip() and row[0].strip().lower() != "ticker":
                out[row[0].strip().upper()] = (today, float(row[1].replace("$", "").replace(",", "")))
    return out


def from_yahoo(tickers):
    import yfinance as yf                         # optional dependency
    out = {}
    data = yf.download(list(tickers), period="5d", interval="1d", progress=False, auto_adjust=False)["Close"]
    for t in tickers:
        col = data[t] if hasattr(data, "columns") and t in data.columns else data
        col = col.dropna()
        if len(col):
            out[t] = (col.index[-1].date().isoformat(), float(col.iloc[-1]))
    return out


def store(con, quotes, source):
    for t, (d, px) in quotes.items():
        con.execute("INSERT OR REPLACE INTO prices VALUES (?,?,?,?)", (t, d, px, source))
    con.commit()


def latest(con):
    q = """SELECT p.ticker, p.date, p.close, p.source FROM prices p
           JOIN (SELECT ticker, MAX(date) d FROM prices GROUP BY ticker) m ON m.ticker = p.ticker AND m.d = p.date"""
    return {r["ticker"]: dict(r) for r in con.execute(q)}
