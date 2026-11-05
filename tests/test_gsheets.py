"""Google Sheets sync, against a fake Google API (no network, no real data)."""
import os, pytest
from trader import gsheets
from trader.sheets import parse_sheet, parse_rows

HEAD = [["Current", "", "", "Price per", "Price"], ["Price", "", "Shares", "Share", "Sold", "Purchased", "Sold"]]


def stock(ticker, price, lots):
    rows = HEAD + [["", "Randol IRA"]]
    for i, (n, cps, bd) in enumerate(lots):
        rows.append([str(price) if i == 0 else "", ticker if i == 0 else "", str(n), f"{cps:,.2f}", "", bd, "", f"{n * cps:,.2f}"])
    rows.append(["", "", str(sum(l[0] for l in lots)), "", "", "", "", "1,000.00"])
    return rows


GOOGL = stock("GOOGL", 280.48, [(14, 250.0, "9/2/2026"), (3, 287.22, "10/29/2026")])
LEU = stock("LEU", 190.0, [(25, 200.0, "8/1/2026")])
SUMMARY = [["Totals"], ["", "everything"], ["1", "2", "3"]]


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self.data


class FakeGoogle:
    """Drive files.list + Sheets get/batchGet over an in-memory {file id: (name, modified, {tab: rows})}."""
    service_account_email = "trader@test.iam.gserviceaccount.com"

    def __init__(self, files, fail=None):
        self.files, self.fail, self.calls = files, fail, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if self.fail and self.fail in url:
            return Resp({"error": {"message": "Google Sheets API has not been used in project 1 or it is disabled"}}, 403)
        if url == gsheets.DRIVE:
            return Resp({"files": [dict(id=i, name=n, modifiedTime=m) for i, (n, m, _) in self.files.items()]})
        sid, _, tail = url[len(gsheets.SHEETS) + 1:].partition("/")
        tabs = self.files[sid][2]
        if not tail:
            return Resp({"sheets": [{"properties": {"title": t}} for t in tabs]})
        assert tail == "values:batchGet" and params["valueRenderOption"] == "FORMATTED_VALUE"
        titles = [r[1:-1].replace("''", "'") for r in params["ranges"]]
        return Resp({"valueRanges": [{"values": tabs[t]} for t in titles]})


def test_fetch_finds_stock_tabs_and_skips_the_rest():
    g = FakeGoogle({"a": ("Dad's stocks", "2026-11-01", {"GOOGL": GOOGL, "Summary": SUMMARY}),
                    "b": ("Uranium", "2026-11-02", {"Sheet1": LEU})})
    sheets, notes = gsheets.fetch(g)
    assert set(sheets) == {"GOOGL", "LEU"}                       # LEU named from the sheet, not "Sheet1"
    assert any("Summary" in n for n in notes)


def test_tab_titles_with_quotes_are_escaped():
    g = FakeGoogle({"a": ("x", "2026-11-01", {"Dad's GOOGL": GOOGL})})
    sheets, _ = gsheets.fetch(g)
    assert "GOOGL" in sheets
    assert g.calls[-1][1]["ranges"] == ["'Dad''s GOOGL'"]


def test_duplicate_ticker_uses_most_recently_edited():
    newer = stock("GOOGL", 280.48, [(18, 250.0, "9/2/2026")])
    g = FakeGoogle({"old": ("GOOGL old", "2026-01-01", {"GOOGL": GOOGL}), "new": ("GOOGL", "2026-11-03", {"GOOGL": newer})})
    sheets, notes = gsheets.fetch(g)
    assert sheets["GOOGL"] is newer and any("more than once" in n for n in notes)


def test_api_error_is_readable():
    with pytest.raises(gsheets.SyncError, match="enable the Google Drive API"):
        gsheets.fetch(FakeGoogle({"a": ("x", "1", {"GOOGL": GOOGL})}, fail="sheets.googleapis"))


def test_written_csvs_parse_like_the_api_rows(tmp_path):
    out = str(tmp_path / "sheets")
    ch = gsheets.write_csvs({"GOOGL": GOOGL, "LEU": LEU}, out)
    assert ch == dict(added=["GOOGL", "LEU"], removed=[], total=2)
    a, b = parse_sheet(os.path.join(out, "GOOGL.csv")), parse_rows(GOOGL, "GOOGL")
    assert a["lots"] == b["lots"] and a["meta"]["current_price"] == 280.48


def test_sync_replaces_old_sheets_but_refuses_a_big_drop(tmp_path):
    out = str(tmp_path / "sheets")
    gsheets.write_csvs({t: stock(t, 10.0, [(500, 10.0, "9/2/2026")]) for t in ("AAA", "BBB", "CCC", "DDD")}, out)
    with pytest.raises(gsheets.SyncError, match="down from 4"):
        gsheets.write_csvs({"AAA": GOOGL}, out)
    assert len(os.listdir(out)) == 4                             # untouched after a refused sync
    ch = gsheets.write_csvs({"AAA": GOOGL, "BBB": GOOGL, "EEE": GOOGL}, out)
    assert ch["removed"] == ["CCC", "DDD"] and ch["added"] == ["EEE"]
    assert sorted(os.listdir(out)) == ["AAA.csv", "BBB.csv", "EEE.csv"]
    gsheets.write_csvs({"AAA": GOOGL}, out, force=True)
    assert os.listdir(out) == ["AAA.csv"]


def test_nothing_shared_is_an_error(tmp_path):
    with pytest.raises(gsheets.SyncError, match="shared"):
        gsheets.write_csvs({}, str(tmp_path / "sheets"))
