# dad-trader

Automates Dad's constant-value trading system. Today it does one job: turn his per-stock Google Sheets
into a **daily rung sheet** — the standing buy and sell limit orders each position should have resting at
the broker. Nothing here places trades.

## The system, as confirmed with Dad (Oct 30, 2026)

- Each position has a constant-dollar **basis**: $2,500, $5,000 or $10,000.
- **Band** on market value (shares × price): ±$200, ±$200, ±$400.
- Above basis + band → sell; below basis − band → buy; **whole shares only**, enough to return to basis.
- Basis stays put after a trade. Trades fire intraday via standing GTC limit orders.
- Picks come from four InvestorPlace services (Growth Investor, Early Stage Investor, Fry's Investment Report,
  Innovation Investor); Dad adds and removes names weekly. Freed cash is redeployed.

## Quick start

```bash
pip install -r requirements.txt           # stdlib only, plus pytest; yfinance optional
# export each stock's Google Sheet as CSV into data/sheets/<TICKER>.csv
python -m trader seed                     # build data/trader.db from the sheets
python -m trader prices --yahoo           # live closes (needs internet + yfinance), or:
python -m trader prices --csv quotes.csv  #   a ticker,price file you maintain
python -m trader rungs                    # -> out/rung-sheet-<date>.html, out/orders-<date>.csv
python -m trader backtest                 # -> out/backtest.md
python -m pytest -q
```

Without a `prices` step, the rung sheet uses the "Current Price" cell from each sheet export.

## Google Sheets sync

Instead of exporting CSVs by hand, `python -m trader sync` reads Dad's sheets straight from Google with a
service account (a robot Google account with read-only access), writes them to `data/sheets/`, and re-seeds.
Positions follow whatever Dad records in his sheets, so fills show up on the next refresh.

One-time setup:

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project (e.g. `dad-trader`).
2. **APIs & Services → Library**: enable **Google Sheets API** and **Google Drive API**.
3. **IAM & Admin → Service Accounts → Create service account** (e.g. `rung-sheet`). No roles needed.
4. Open it → **Keys → Add key → JSON**. Save the file as `data/service-account.json` (git-ignored). Treat it
   like a password.
5. Have Dad **share** each stock sheet, or better the folder that holds them, with the service account's email
   (`rung-sheet@<project>.iam.gserviceaccount.com`) as **Viewer**. Sheets he adds to a shared folder later
   are picked up automatically.

```bash
pip install google-auth requests
python -m trader sync              # or --key path/to/key.json, or set TRADER_SA_KEY
```

Every spreadsheet the service account can see is read tab by tab. A tab is a stock sheet if it has lot rows;
its ticker comes from the sheet itself (the current-price row), else the tab name, else the file name. Other
tabs are skipped and listed. If a sync fails, or would drop more than half of the sheets (say a folder got
unshared), nothing is replaced; `--force` overrides the second check. The rung sheet shows where positions
came from and when.

On the server: `bash deploy/install.sh --key service-account.json` stores the key in
`/etc/dad-trader/` (mode 600) and `publish.sh` syncs before every refresh.

## AI chat

The rung sheet has an **Ask AI** button (bottom right) for questions like "why is AGX on the review list?" or
"any news on my act-now stocks?". Answers come from Google Gemini, which is given the current positions,
orders, grades and newsletters, and can search the web for news (with source links).

The API key stays on the server, so the chat needs the app server, not the plain HTML file:

```bash
export GEMINI_API_KEY=...          # from https://aistudio.google.com/apikey
python -m trader serve             # open http://localhost:8000
```

`GEMINI_MODEL` overrides the model (default `gemini-flash-latest`). The server binds to 127.0.0.1 only, takes
same-origin JSON only, and allows 30 questions a minute. Conversation history lives in the browser tab.

On EC2, `install.sh` asks for the key once (stored in `/etc/dad-trader/gemini.env`, mode 600), runs the backend
as the `dad-trader-chat` systemd service on port 8001, and has httpd/nginx pass `/chat` to it behind the same
password login.

> **Privacy:** every question sends Dad's positions to Google. On Gemini's **free tier, Google may use prompts
> to improve its products**; on a paid (billing-enabled) key it doesn't. For his financial data, turn on
> billing for the key. Casual use costs pennies a month.

## CI/CD

Changes go through pull requests. **The one click is "Merge pull request".** Everything after it is automatic.

1. Push a branch and open a PR. **CI** (`.github/workflows/ci.yml`) runs the tests on Python 3.11.
2. When CI is green, click **Merge**.
3. **Deploy** (`.github/workflows/deploy.yml`) runs the tests again on `main`, ships the commit to EC2 over SSH,
   and runs `deploy/update.sh`. That script tests the code on the server, snapshots the running version,
   swaps in the new code, restarts the chat backend, republishes the rung sheet, and **rolls back** if any of
   that fails. Then it checks that https://trader.wellslabs.dev answers.
4. The Actions tab has the log of every test and deploy; `/opt/dad-trader/RELEASE` on the server shows the
   live commit. Redeploy by hand: Actions → Deploy → **Run workflow**.

`update.sh` only updates app code. Re-run `deploy/install.sh` by hand when packages, cron, the web server
config, systemd or the keys change. Roll back by hand: `ls -t ~/releases` on the server, then
`bash ~/releases/<sha>/deploy/update.sh <sha>`.

> [!NOTE]
> On GitHub Free, private repos can't use branch protection or deployment approvals, so GitHub won't *stop*
> you from merging a red PR. Deploy still re-runs the tests and won't ship if they fail. GitHub Pro adds
> "require CI to pass before merging" (Settings → Branches).

One-time setup:

1. **Server is on the current code.** Ship this version once the old way (zip + `install.sh`) so the chat
   service and keys are in place.
2. **Deploy key** (on your Mac). A separate key just for GitHub, so you can revoke it without touching yours:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/dad-trader-deploy -N "" -C "github-actions deploy"
   ssh -i KEY.pem ec2-user@trader.wellslabs.dev 'cat >> ~/.ssh/authorized_keys' < ~/.ssh/dad-trader-deploy.pub
   ssh-keyscan -t ed25519 trader.wellslabs.dev      # copy this line for EC2_KNOWN_HOSTS
   ```
   Check the scanned key matches the `trader.wellslabs.dev` line in your own `~/.ssh/known_hosts`.
3. **EC2 security group**: allow inbound SSH (22) from anywhere. GitHub's runners don't have fixed IPs.
   EC2 only allows key logins by default; keep it that way.
4. **GitHub secrets** (repo → Settings → Secrets and variables → Actions → New repository secret):
   `EC2_HOST` = `trader.wellslabs.dev`, `EC2_USER` = `ec2-user`, `EC2_SSH_KEY` = contents of
   `~/.ssh/dad-trader-deploy` (the private key), `EC2_KNOWN_HOSTS` = the `ssh-keyscan` line.
5. **Optional**: Settings → General → turn on "Automatically delete head branches".

## Deploy to the EC2 server (RHEL 8/9)

```bash
scp -i KEY.pem dad-trader.zip data/service-account.json ec2-user@trader.wellslabs.dev:~     # from your Mac
ssh -i KEY.pem ec2-user@trader.wellslabs.dev
unzip -oq dad-trader.zip && cd dad-trader && bash deploy/install.sh --https you@example.com --key ~/service-account.json
rm ~/service-account.json                                          # installed copy lives in /etc/dad-trader/
```

`deploy/install.sh` finds nginx or httpd, installs Python 3.11, copies the app to `/opt/dad-trader`, seeds the
database, publishes the rung sheet as the site's `index.html`, asks for passwords for users `dad` and `jeff`,
schedules refreshes (weekdays 8:30, 12:00, 3:15 Central), and with `--https` gets a Let's Encrypt certificate.
With `--key`, each refresh first syncs Dad's Google Sheets. Re-run it after updating the zip; it keeps the
passwords and the key (no need to pass `--key` again). Refresh by hand: `/opt/dad-trader/publish.sh`.
Keep the service account key out of the zip.

## Layout

| File | What it does |
|---|---|
| `trader/sheets.py` | Parses Dad's sheet layout: lots, account blocks, totals rows, footer metadata (grade, Zacks, newsletters, Buy Below) |
| `trader/gsheets.py` | Google Sheets sync: service-account auth, finds shared stock sheets, writes them to `data/sheets/` |
| `trader/chat.py` | AI chat: ledger snapshot as context, Gemini API call with Google Search grounding |
| `trader/server.py` | `serve`: rung sheet rendered live + `POST /chat` (stdlib `http.server`) |
| `trader/chat_widget.py` | The Ask AI panel (HTML/CSS/JS) embedded in every rung sheet |
| `trader/db.py` | SQLite schema. Positions keyed on **(account, ticker)** — he holds some tickers in two accounts |
| `trader/history.py` | Lots → trades; infers each position's basis from where it settles after trades |
| `trader/seed.py` | Loads the sheets; classifies each position as `system` (laddered) or `hold` (listed for review) |
| `trader/engine.py` | The rule: trade sizing, rung prices, act-now detection |
| `trader/backtest.py` | Replays every historical trade and scores the engine against what Dad did |
| `trader/report.py` | Rung sheet HTML + orders CSV |
| `trader/prices.py` | Price sources: sheet snapshot, CSV, Yahoo |

## What the pilot found (25 sheets, 1,864 trades)

- Three accounts: Randol IRA, June IRA, Randol Fidelity. AGX, CLS, CRS, PANW, RDW, AUR are held in two.
- **Not everything is the system.** Randol IRA bought AGX, CRS and RDW as single blocks on Aug 20, 2026
  (all tagged *A/I Revolution Portfolio*) and hasn't rebalanced them. Those, and stale Fidelity lots, are
  classified `hold` and get no rungs.
- Engine vs history: same direction 70%, exact share count 36%, within 25% of his size 61%.
  Buys on $100+ stocks match best (70–80% exact on GOOGL, CLS, PANW, CRS).
- `nearest` rounding matches his trades slightly better than `above` (36% vs 35% exact; sells 36% vs 33%).
  Default is `nearest`; `--rounding above` is available.
- He trades inside the ±$200 band about 29% of the time and often lets drift run to $300+. The rule is
  enforced as stated; tuning rung spacing per position is the next step.

## Open questions for Dad

1. Cheap stocks (ACHR, ENVX, AUR): how does he pick the share count when selling into a bounce?
2. Where does he place standing orders — how far from basis, how many at once?
3. Are *Green Zone Fortunes* and *A/I Revolution Portfolio* active sources? Is the A/I block a separate strategy?
4. Is the Randol Fidelity account part of the system at all?

## Not built yet

Newsletter ingest (portfolio-page diff + alert parsing), tier-up/down recommendations, weekly add/drop review,
fill entry / reconciliation, broker execution.

Dad's sheet exports, the database and generated output are financial data and are git-ignored.
