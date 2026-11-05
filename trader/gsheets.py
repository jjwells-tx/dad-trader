"""Pull Dad's stock sheets straight from Google Sheets with a service account.

Every spreadsheet shared with the service account (directly, or through a shared folder) is read, tab by tab.
A tab counts as a stock sheet if it has lot rows; its ticker comes from the sheet itself (column B of the
current-price row), falling back to the tab name, then the file name. Each one is written to
data/sheets/<TICKER>.csv in the same shape as a manual CSV export, so `seed` and everything after it is unchanged.

The swap into data/sheets/ only happens after every sheet was read successfully, so a failed sync leaves the
last good copies in place.

Setup: see "Google Sheets sync" in README.md.
"""
import csv, os, shutil
from .sheets import parse_rows, detect_ticker, TICKER_RE

SCOPES = ["https://www.googleapis.com/auth/drive.readonly",
          "https://www.googleapis.com/auth/spreadsheets.readonly"]
DRIVE = "https://www.googleapis.com/drive/v3/files"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"
MIN_KEEP = 0.5   # refuse to sync if we'd end up with fewer than half the sheets we had (use --force to override)


class SyncError(Exception):
    pass


def open_session(key_path):
    """An authorized requests session for the service account key at `key_path`."""
    if not os.path.exists(key_path):
        raise SyncError(f"No service account key at {key_path}. See 'Google Sheets sync' in README.md.")
    from google.oauth2 import service_account                      # optional dependency: pip install google-auth
    from google.auth.transport.requests import AuthorizedSession
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    session = AuthorizedSession(creds)
    session.service_account_email = creds.service_account_email
    return session


def _get(session, url, params):
    r = session.get(url, params=params, timeout=60)
    if r.status_code != 200:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text[:300]
        hint = ""
        if r.status_code == 403 and ("has not been used" in msg or "disabled" in msg):
            hint = " (enable the Google Drive API and Google Sheets API in the service account's Cloud project)"
        raise SyncError(f"Google API error {r.status_code} on {url}: {msg}{hint}")
    return r.json()


def list_spreadsheets(session):
    """Every spreadsheet the service account can see: [{id, name, modifiedTime}]."""
    files, token = [], None
    while True:
        params = dict(q=f"mimeType='{SPREADSHEET_MIME}' and trashed=false", pageSize=1000,
                      fields="nextPageToken, files(id, name, modifiedTime)",
                      supportsAllDrives="true", includeItemsFromAllDrives="true")
        if token:
            params["pageToken"] = token
        page = _get(session, DRIVE, params)
        files += page.get("files", [])
        token = page.get("nextPageToken")
        if not token:
            return files


def _a1(title):
    return "'" + title.replace("'", "''") + "'"


def read_tabs(session, spreadsheet_id):
    """[(tab title, rows of formatted cell text)] for every tab in one spreadsheet."""
    info = _get(session, f"{SHEETS}/{spreadsheet_id}", dict(fields="sheets.properties(title)"))
    titles = [s["properties"]["title"] for s in info.get("sheets", [])]
    if not titles:
        return []
    # FORMATTED_VALUE is what a CSV export contains: "4,327.84", "10/29/2026", ...
    data = _get(session, f"{SHEETS}/{spreadsheet_id}/values:batchGet",
                dict(ranges=[_a1(t) for t in titles], valueRenderOption="FORMATTED_VALUE", majorDimension="ROWS"))
    return [(t, vr.get("values", [])) for t, vr in zip(titles, data.get("valueRanges", []))]


def resolve_ticker(rows, tab_title, file_name):
    for cand in (detect_ticker(rows), tab_title.strip(), file_name.strip()):
        if cand and TICKER_RE.fullmatch(cand):
            return cand
    return None


def fetch(session):
    """Read every shared spreadsheet. Returns ({ticker: rows}, notes) where notes explain anything skipped."""
    found, notes = {}, []
    files = sorted(list_spreadsheets(session), key=lambda f: f.get("modifiedTime", ""))   # newest wins on duplicates
    for f in files:
        for title, rows in read_tabs(session, f["id"]):
            where = f"'{f['name']}' / tab '{title}'"
            ticker = resolve_ticker(rows, title, f["name"])
            if not ticker:
                notes.append(f"skipped {where}: no ticker found")
                continue
            if not parse_rows(rows, ticker)["lots"]:
                notes.append(f"skipped {where}: no lot rows (not a stock sheet)")
                continue
            if ticker in found:
                notes.append(f"{ticker} appears more than once; using the most recently edited copy, {where}")
            found[ticker] = rows
    return found, notes


def write_csvs(sheets, out_dir="data/sheets", force=False):
    """Replace the CSVs in out_dir with `sheets` ({ticker: rows}), all or nothing."""
    before = {f[:-4] for f in os.listdir(out_dir) if f.endswith(".csv")} if os.path.isdir(out_dir) else set()
    if not sheets:
        raise SyncError("No stock sheets found. Has Dad shared his sheets (or their folder) with the service account?")
    if not force and before and len(sheets) < MIN_KEEP * len(before):
        missing = ", ".join(sorted(before - set(sheets)))
        raise SyncError(f"Only {len(sheets)} sheets found, down from {len(before)} (missing: {missing}). "
                        "If that's expected, re-run with --force.")
    out_dir = out_dir.rstrip("/")
    tmp, old = out_dir + ".new", out_dir + ".old"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for ticker, rows in sheets.items():
        with open(os.path.join(tmp, f"{ticker}.csv"), "w", newline="") as fh:
            csv.writer(fh).writerows(rows)
    if os.path.exists(os.path.join(out_dir, ".gitkeep")):
        open(os.path.join(tmp, ".gitkeep"), "w").close()
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(out_dir):
        os.rename(out_dir, old)
    os.rename(tmp, out_dir)
    shutil.rmtree(old, ignore_errors=True)
    return dict(added=sorted(set(sheets) - before), removed=sorted(before - set(sheets)), total=len(sheets))
