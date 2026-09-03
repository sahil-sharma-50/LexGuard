# Lexguard Paper Trading Runbook

This runbook is for an authorized operator running Lexguard against an Alpaca
paper account. It covers setup, readiness checks, controlled entry enablement,
runtime operation, and evidence export.

For a quick local walkthrough, start with README.md. The public Training Room
is synthetic and does not require credentials. The procedures below can read
broker data and can submit paper orders when entry is explicitly enabled.

## Operating rules

- Use only https://paper-api.alpaca.markets.
- Use a dedicated paper account for competition activity.
- Keep entry disabled until the account, database, MCP server, artifacts, and
  reconciliation checks are healthy.
- The operator controls are stop-only. They can pause, resume, emergency-stop,
  or veto a case, but they cannot initiate a trade.
- Do not publish credentials, account identifiers, private exports, or
  unredacted broker responses.

## 1. One-time setup

The Docker workflow is the preferred local setup. Native commands are included
for macOS, Linux, and WSL.

### Docker

~~~bash
make setup
# Edit .env with Alpaca paper credentials and an OpenAI API key.
make up
make preflight
~~~

On Windows PowerShell:

~~~powershell
Copy-Item .env.example .env
# Edit .env, then run:
.\run-docker.ps1
docker compose run --rm --no-deps api run-preflight
~~~

### Native

Requirements: Python 3.12 through 3.14, uv, Node.js 22 or newer, pnpm,
PostgreSQL, and the official Alpaca MCP server checkout.

The native helper expects the MCP checkout at alpaca-mcp-server-main:

~~~bash
git clone https://github.com/alpacahq/alpaca-mcp-server.git alpaca-mcp-server-main
make native-setup
make -f Makefile.native db
~~~

Create .env from .env.example and keep these native values:

~~~text
ALPACA_BASE_URL=https://paper-api.alpaca.markets
LEXGUARD_MCP_URL=http://127.0.0.1:8010/mcp
LEXGUARD_ENTRY_ENABLED=false
~~~

## 2. Verify the account

Create the final competition paper account in the Alpaca dashboard only when
the competition requires it. Confirm that the account has the required
options level, is active, and is flat. Keep its account ID outside the
repository until it is deliberately added to the final submission.

From the repository root:

~~~bash
cd agent
.venv/bin/lexguard verify-account
.venv/bin/lexguard verify-account --competition
cd ..
~~~

The competition check is an operator gate. It must not be replaced with a
local fixture or a guessed account value.

## 3. Start the evidence boundary

The agent reads observable market data through the official Alpaca MCP server.
Run the server over streamable HTTP when operating natively:

~~~bash
cd alpaca-mcp-server-main
ALPACA_API_KEY=... ALPACA_SECRET_KEY=... ALPACA_PAPER_TRADE=true \
  uv run alpaca-mcp-server --transport streamable-http --port 8010
~~~

In another terminal, verify the native environment points to:

~~~text
LEXGUARD_MCP_URL=http://127.0.0.1:8010/mcp
~~~

The Docker stack starts this service automatically.

Optional read-only MCP smoke test:

~~~bash
cd agent
LEXGUARD_RUN_ALPACA_SMOKE=1 .venv/bin/python -m pytest -m alpaca_smoke
cd ..
~~~

## 4. Seed runtime artifacts

Risk state is durable and forecast artifacts are hash-verified. Seed them
after migrations and before enabling entries:

~~~bash
cd agent
.venv/bin/lexguard seed-risk-state
.venv/bin/lexguard seed-forecast --symbol SPY
.venv/bin/lexguard seed-forecast --symbol QQQ
.venv/bin/lexguard seed-forecast --symbol IWM
cd ..
~~~

Per-symbol forecast artifacts use
LEXGUARD_FORECAST_ARTIFACT_PATH_<SYMBOL> when configured. Otherwise the
default artifact path is used.

## 5. Run readiness checks

~~~bash
cd agent
.venv/bin/lexguard run-preflight
cd ..
~~~

The command should return ready true. Fix every named blocker and rerun the
check. Common blockers include an unmigrated database, unavailable broker or
MCP service, stale forecast artifacts, a non-paper endpoint, missing risk
state, or a non-flat account.

## 6. Enable entries explicitly

Do not enable entries until the preceding checks are complete:

~~~bash
cd agent
.venv/bin/lexguard enable-entries --environment development --acknowledge-paper-only
cd ..
~~~

Use competition instead of development only for the dedicated competition
account. The global environment gate and the database-backed operator control
must both permit entries.

Disable entries at any time:

~~~bash
cd agent
.venv/bin/lexguard disable-entries
cd ..
~~~

The authenticated pause endpoint has the same effect for the next scheduler
tick.

## 7. Run the services

### Native

Start at least ten minutes before a decision window:

~~~bash
make native-dev
~~~

The helper starts the MCP server, API, scheduler, and web application. Logs
are written to .dev-logs. Stop all native services with:

~~~bash
make native-stop
~~~

### Docker

~~~bash
make up
make logs
~~~

The Docker scheduler runs in watch mode and seeds its runtime artifacts during
startup.

Decision windows use America/New_York: 10:05, 11:35, 13:05, and 14:20. The
scheduler executes five minutes after each window. It retries failed preflight
every 30 seconds, rechecks readiness every five minutes, refreshes durable
risk state every 60 seconds, and ticks every five seconds. Positions are
force-flat by 15:30 ET.

## 8. Operator controls

The API controls require the X-Operator-Token header:

~~~bash
curl -X POST \
  -H "X-Operator-Token: $LEXGUARD_OPERATOR_TOKEN" \
  http://localhost:8000/api/controls/pause

curl -X POST \
  -H "X-Operator-Token: $LEXGUARD_OPERATOR_TOKEN" \
  http://localhost:8000/api/controls/resume

curl -X POST \
  -H "X-Operator-Token: $LEXGUARD_OPERATOR_TOKEN" \
  http://localhost:8000/api/controls/emergency-stop

curl -X POST \
  -H "X-Operator-Token: $LEXGUARD_OPERATOR_TOKEN" \
  http://localhost:8000/api/cases/<case-id>/veto
~~~

Controls write ledger artifacts. The scheduler applies them on its next tick.
No HTTP route can submit, replace, or cancel an order.

## 9. Daily evidence ritual

Run after the market close and before publishing any performance statement:

~~~bash
cd agent
.venv/bin/lexguard daily-report
.venv/bin/lexguard export-evidence --environment development
cd ..
agent/.venv/bin/python scripts/export_competition_evidence.py --environment development
~~~

For competition activity, use the competition environment in every export
command. Evidence bundles belong in the ignored artifacts directory until
they are redacted and intentionally selected for publication. Order IDs may
be retained as join keys for judge verification. Account IDs and credentials
must remain private.

## Feed disclosure

LEXGUARD_OPTION_FEED=indicative uses Alpaca's free derived options feed.
LEXGUARD_OPTION_FEED=opra requires the appropriate subscription. The selected
feed is enforced as quote provenance and must be disclosed with any results.

## Failure response

If broker truth, the ledger, evidence, or the scheduler disagree:

1. Disable entries.
2. Use the emergency-stop control if the state is uncertain.
3. Do not manually edit ledger artifacts or reset runtime state.
4. Capture the named blocker and the relevant timestamps.
5. Reconcile against the Alpaca paper account before resuming.
