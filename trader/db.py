"""SQLite ledger. Every position is keyed on (account, ticker) — Dad holds some tickers in two accounts."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    ticker       TEXT PRIMARY KEY,
    grade        TEXT,          -- Stock Grader / Portfolio Grader (A-F)
    zacks        TEXT,          -- Zacks rank 1-5
    buy_below    REAL,          -- lowest Buy Below across newsletters (the stricter one)
    newsletters  TEXT,          -- JSON list of {name, bucket, date, price}
    high_52w     REAL,
    target_1y    REAL,
    status       TEXT DEFAULT 'active'   -- active | sell_all | watch
);

CREATE TABLE IF NOT EXISTS positions (
    account   TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    shares    INTEGER NOT NULL,
    basis     REAL NOT NULL,     -- 2500 / 5000 / 10000 constant-dollar target
    band      REAL NOT NULL,     -- 200 / 200 / 400
    style     TEXT NOT NULL DEFAULT 'system',  -- system = constant-value ladder | hold = buy-and-hold, no rungs
    note      TEXT,
    last_trade TEXT,
    PRIMARY KEY (account, ticker)
);

CREATE TABLE IF NOT EXISTS basis_changes (
    account   TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    basis     REAL NOT NULL,
    effective TEXT NOT NULL,     -- ISO date
    reason    TEXT               -- seed | dad | recommendation
);

CREATE TABLE IF NOT EXISTS lots (
    id        INTEGER PRIMARY KEY,
    account   TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    shares    INTEGER NOT NULL,
    cost_ps   REAL NOT NULL,
    buy_date  TEXT NOT NULL,
    sell_px   REAL,
    sell_date TEXT
);

CREATE TABLE IF NOT EXISTS prices (
    ticker  TEXT NOT NULL,
    date    TEXT NOT NULL,
    close   REAL NOT NULL,
    source  TEXT,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS tickets (
    id        INTEGER PRIMARY KEY,
    created   TEXT NOT NULL,
    account   TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    side      TEXT NOT NULL,     -- BUY | SELL
    shares    INTEGER NOT NULL,
    limit_px  REAL NOT NULL,
    reason    TEXT,              -- upper_rung | lower_rung | act_now | sell_all | new
    status    TEXT DEFAULT 'proposed',   -- proposed | placed | filled | cancelled | dry_run
    fill_px   REAL,
    fill_date TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,   -- positions_source | positions_loaded
    value  TEXT
);
"""

TIERS = {2500: 200, 5000: 200, 10000: 400}


def connect(path="data/trader.db"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
