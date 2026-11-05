"""End-to-end smoke test on the real sheet exports, if they're present.

Works with any subset of Dad's sheets (e.g. the BE/CAT/VOYG proof of concept). Checks pinned to specific
positions run only when those sheets are there.
"""
import glob, os, pytest
from trader.seed import seed
from trader.db import connect
from trader.report import build_plan
from trader.backtest import run, summarize

SHEETS = "data/sheets/*.csv"
pytestmark = pytest.mark.skipif(not glob.glob(SHEETS), reason="no sheet exports in data/sheets")
HAVE = {os.path.basename(p)[:-4] for p in glob.glob(SHEETS)}
needs = lambda *t: pytest.mark.skipif(not set(t) <= HAVE, reason=f"needs {', '.join(t)} sheets")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("pipe") / "t.db")
    loaded, _ = seed(SHEETS, path, as_of="2026-10-30")
    assert loaded
    return path


def test_every_position_gets_a_plan(db):
    con = connect(db)
    n = con.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    plans = build_plan(db)
    assert n > 0 and len(plans) == n
    for p in plans:
        assert p["status"] in ("ok", "act_now", "review", "hold", "no_price", "closed")
        if p["status"] in ("ok", "act_now"):
            assert p["sells"] and p["buys"]
            assert p["sells"][0]["limit"] > p["price"] or p["status"] == "act_now"


def test_backtest_runs(db):
    _, tot = summarize(run(db))
    assert tot["trades"] > 0


@needs("AGX")
def test_positions_keyed_on_account_and_ticker(db):
    # AGX is held in both IRAs
    assert connect(db).execute("SELECT COUNT(*) FROM positions WHERE ticker='AGX'").fetchone()[0] == 2


@needs("GOOGL", "RDW")
def test_known_rungs_and_holds(db):
    plans = {(p["account"], p["ticker"]): p for p in build_plan(db)}
    g = plans[("Randol IRA", "GOOGL")]
    assert g["status"] == "ok" and g["sells"][0]["limit"] == 288.89 and g["buys"][0]["limit"] == 266.66
    # the Aug 20 block buys are buy-and-hold, not laddered
    assert plans[("Randol IRA", "RDW")]["status"] == "hold"


@pytest.mark.skipif(len(HAVE) < 20, reason="needs the full sheet set")
def test_full_history_backtest(db):
    _, tot = summarize(run(db))
    assert tot["trades"] > 1500 and tot["side"] >= 60
