# Lexguard

> AI argues. Risk decides.

Lexguard is a paper-only autonomous options trading system built for the
Alpaca AI Trading Agents Hackathon. It combines market evidence, calibrated
forecasting, a bounded OpenAI catalyst argument, deterministic risk controls,
and Alpaca paper execution in one replayable case file.

The central design rule is simple: the model may explain a scenario or veto a
case, but it cannot choose contracts, strikes, quantity, price, or broker
actions. Deterministic code owns the risk certificate and the execution
boundary.

> Important: Lexguard is a software project and research prototype. It is not
> investment advice. It is configured for Alpaca paper trading only and must
> not be pointed at a live brokerage account.

## What the project does

Each decision window follows the same fail-closed sequence:

| Stage | Responsibility | Result |
| --- | --- | --- |
| Observe | Read the clock, account, bars, option chain, positions, orders, and news through the official Alpaca MCP server. | A content-hashed evidence snapshot |
| Forecast | Estimate the remaining intraday move from completed historical bars. | A versioned forecast artifact |
| Argue | Ask the OpenAI catalyst component to classify the supplied evidence into one fixed scenario or veto. | A structured, cited argument |
| Certify | Generate valid four-leg condor candidates and apply deterministic policy gates. | One trade certificate or an explicit refusal |
| Execute | Submit one atomic mleg limit order through Alpaca Trading API. | A broker order lifecycle |
| Reconcile | Compare broker truth with the append-only ledger after each mutation. | A consistent result or a halt |

The default decision windows are 10:05, 11:35, 13:05, and 14:20 in
America/New_York. The strategy evaluates SPY, QQQ, and IWM and uses covered,
equal-ratio, same-expiration four-leg structures with 1 to 3 days to expiry.
Positions are force-flat by 15:30 ET.

## Why it is different

- The AI has a narrow, inspectable role. Invalid, stale, unavailable, or
  uncited model output becomes a veto.
- Risk is deterministic. The judge recomputes payoff and enforces trade,
  daily, drawdown, evidence, quote, timing, position, and certificate gates.
- Execution is atomic. The system submits one four-leg mleg order and
  reconciles the original and any replacement against broker state.
- Abstention is a valid outcome. Refusals and their reason codes become part of
  the case record instead of being hidden as missing data.
- The browser-facing Training Room is synthetic and browser-local. Its
  actions never call Alpaca and never mutate external state.
- Public projections are redacted. Credentials, account identifiers, and
  private broker exports remain outside the anonymous web experience.

## Quickstart with Docker

Docker is the recommended local path because it starts the database, the
official Alpaca MCP server, the API, the scheduler, and the web application
with one command.

### Prerequisites

- Docker Desktop with Docker Compose v2, or Docker Engine with Compose v2
- An Alpaca paper account and paper API key pair
- An OpenAI API key

### 1. Create the environment file

macOS, Linux, or WSL:

~~~bash
make setup
~~~

Windows PowerShell:

~~~powershell
Copy-Item .env.example .env
~~~

Open .env and set ALPACA_API_KEY, ALPACA_SECRET_KEY, and OPENAI_API_KEY.
Keep ALPACA_BASE_URL set to the paper endpoint. Leave
LEXGUARD_ENTRY_ENABLED=false while developing.

Never commit .env or place secrets in a NEXT_PUBLIC_* variable.

### 2. Start the stack

macOS, Linux, or WSL:

~~~bash
make up
make preflight
~~~

Windows PowerShell:

~~~powershell
.\run-docker.ps1
~~~

The first build can take a few minutes. The migration job runs before the API
and scheduler start. Preflight should report ready true when the credentials,
database, MCP server, forecast artifacts, and broker checks are available.

Open the web application at http://localhost:3000.

Useful Docker commands:

~~~bash
make logs
make ps
make seed
make migrate
make down
~~~

PowerShell users can use the equivalent Docker Compose commands:

~~~powershell
docker compose logs -f
docker compose ps
docker compose down
~~~

The Docker Compose project contains five long-running services and one
one-shot migration job:

- postgres: durable local database
- mcp: official Alpaca MCP server
- api: FastAPI read projections and stop-only controls
- scheduler: autonomous decision and reconciliation loop
- web: Next.js application
- migrate: Alembic migration job that completes before api starts

## Native development

Native development is optional and is intended for macOS, Linux, or WSL. It
requires:

- Python 3.12 through 3.14
- uv
- Node.js 22 or newer
- pnpm
- PostgreSQL
- A local checkout of the official Alpaca MCP server

The native helper expects that server at alpaca-mcp-server-main. If it is not
already present, fetch it from the official repository:

~~~bash
git clone https://github.com/alpacahq/alpaca-mcp-server.git alpaca-mcp-server-main
~~~

Then install dependencies, initialize the database, seed local artifacts, and
start the services:

~~~bash
make native-setup
make -f Makefile.native db
make -f Makefile.native seed
make native-dev
~~~

Stop the native services with:

~~~bash
make native-stop
~~~

For Windows without WSL, use the Docker workflow above.

## Web routes

| Route | Purpose |
| --- | --- |
| / | Public product overview |
| /command | Live command center with account, positions, orders, agent feed, and stop-only controls |
| /cases/current | Current live case projection |
| /cases | Repository-backed case archive |
| /cases/{case-id} | Individual case file |
| /research | Research status and evidence availability |
| /console | Synthetic Training Room overview |
| /console/decision-room | Synthetic browser-local decision simulation |
| /console/cases | Synthetic browser-local case queue |

The live command center requires the API service. The Training Room is
deliberately isolated from the API and can be explored without broker calls.

## Configuration

The root .env.example contains the complete starter configuration. The most
important settings are:

| Variable | Purpose |
| --- | --- |
| ALPACA_BASE_URL | Must remain https://paper-api.alpaca.markets |
| ALPACA_API_KEY and ALPACA_SECRET_KEY | Alpaca paper credentials |
| OPENAI_API_KEY | Key used by the catalyst argument component |
| DATABASE_URL | PostgreSQL connection string; Docker overrides this internally |
| LEXGUARD_MCP_URL | MCP endpoint; Docker overrides this to the mcp service |
| LEXGUARD_ENVIRONMENT | development or competition |
| LEXGUARD_ENTRY_ENABLED | Global entry gate, false by default |
| LEXGUARD_OPTION_FEED | indicative or opra, with provenance enforced in the pipeline |
| LEXGUARD_UNDERLYING_ROTATION | Optional comma-separated symbol sequence |
| LEXGUARD_MAX_ENTRIES_PER_DAY | Maximum number of entries allowed per trading day |
| LEXGUARD_OPERATOR_TOKEN | Token for pause, resume, emergency stop, and case veto controls |
| NEXT_PUBLIC_API_BASE_URL | Browser-safe API origin used by the web app |

The public web app must never receive Alpaca credentials. The operator token
is held in memory by the browser control surface and is not written to web
storage.

## Verification and tests

Run the canonical offline verification from the repository root:

~~~bash
make verify
~~~

Windows PowerShell:

~~~powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
~~~

Verification covers:

- Python linting with ruff
- Python type checking with mypy
- Python unit and contract tests with pytest
- Web font manifest verification
- TypeScript checking
- Web unit tests with Vitest
- Next.js production build

The offline suite does not require network access. Optional integration smoke
tests are explicitly opt-in:

~~~bash
cd agent
LEXGUARD_RUN_ALPACA_SMOKE=1 .venv/bin/python -m pytest -m alpaca_smoke
LEXGUARD_RUN_OPENAI_SMOKE=1 .venv/bin/python -m pytest -m openai_smoke
~~~

Use paper credentials for any smoke test. These checks can call external
services and should not be enabled accidentally in CI.

## Repository layout

~~~text
agent/
  Python package containing the FastAPI service, scheduler, risk domain,
  Alpaca adapters, SQLAlchemy ledger, and research CLI.
web/
  Next.js command center, public projections, case archive, and Training Room.
docs/
  Operator runbook, research methodology, submission drafts, and design notes.
infra/
  Dockerfiles and Railway/Vercel deployment configuration.
scripts/
  Cross-platform verification, local service orchestration, and evidence export.
docker-compose.yml
  Local multi-service development stack.
.env.example
  Safe configuration template with placeholders only.
~~~

## Safety and data handling

Lexguard is intentionally fail-closed:

- Settings, the broker adapter, the MCP gateway, and policy checks reject
  non-paper Alpaca endpoints.
- Unknown broker state, stale or future evidence, missing risk state,
  unavailable data, invalid model output, and reconciliation mismatches cannot
  authorize an entry.
- HTTP routes can read projections and write stop-only control artifacts. No
  HTTP route can submit, replace, or cancel a broker order.
- The scheduler owns autonomous decisions. A human can pause, resume, trigger
  an emergency stop, or veto a pending case, but cannot initiate a trade.
- Generated artifacts, private exports, local environments, dependency
  folders, and runtime caches are excluded by .gitignore.

If you discover a credential or private account data in the working tree,
stop, rotate the credential, remove the file from the working tree, and review
the repository history before publishing.

## Evidence and current status

The repository includes implementation, deterministic fixtures, automated
tests, and public replay surfaces. It does not claim live performance that has
not been verified. The development paper-forward report is marked
NOT_STARTED until an authorized operator produces reconciled Alpaca evidence.

Submission drafts and evidence requirements live in docs/submission. Replace
their placeholders only with real, redacted artifacts from the final
competition paper account.

See these documents for more detail:

- docs/runbook.md for paper-session setup and operator procedures
- infra/DEPLOY.md for Railway and Vercel deployment
- docs/research/methodology.md for the historical research contract
- docs/research/paper-forward-report.md for the evidence gate
- docs/submission/ for presentation and claim tracking
- PRODUCT.md for product requirements
- DESIGN.md for the visual system and interface decisions

## Contributing

Read CONTRIBUTING.md before opening a pull request. Keep changes focused,
preserve the paper-only boundary, add or update tests for behavior changes,
and run the canonical verification command before submitting.

## License

This repository does not currently include a license file. Unless the owner
adds a license, all rights are reserved.
