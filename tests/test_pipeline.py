"""End-to-end smoke test on the real sheet exports, if they're present."""
import glob, os, pytest
from trader.seed import seed
from trader.db import connect
from trader.report import build_plan
from trader.backtest import run, summarize

SHEETS = "data/sheets/*.csv"
pytestmark = pytest.mark.skipif(not glob.glob(SHEETS), reason="no sheet exports in data/sheets")


def test_seed_rungs_backtest(tmp_path):
    db = str(tmp_path / "t.db")
    loaded, _ = seed(SHEETS, db, as_of="2026-10-30")
    con = connect(db)
    accounts = {r[0] for r in con.execute("SELECT DISTINCT account FROM positions")}
    assert {"Randol IRA", "June IRA"} <= accounts
    # positions are keyed on (account, ticker): AGX is held in both IRAs
    assert con.execute("SELECT COUNT(*) FROM positions WHERE ticker='AGX'").fetchone()[0] == 2
    plans = {(p["account"], p["ticker"]): p for p in build_plan(db)}
    g = plans[("Randol IRA", "GOOGL")]
    assert g["status"] == "ok" and g["sells"][0]["limit"] == 288.89 and g["buys"][0]["limit"] == 266.66
    # the Aug 20 block buys are buy-and-hold, not laddered
    assert plans[("Randol IRA", "RDW")]["status"] == "hold"
    _, tot = summarize(run(db))
    assert tot["trades"] > 1500 and tot["side"] >= 60
