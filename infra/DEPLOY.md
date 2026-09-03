# Deployment guide

Lexguard can be deployed with Railway for the database and Python services,
plus Vercel for the Next.js web application. This guide describes the
production-shaped paper-trading topology. It does not create an Alpaca
account, enable entries, or submit an order.

## Deployment topology

| Service | Platform | Configuration | Purpose |
| --- | --- | --- | --- |
| postgres | Railway PostgreSQL | Railway-managed | Durable case ledger and runtime artifacts |
| api | Railway | infra/railway.toml | FastAPI projections and stop-only controls |
| scheduler | Railway | infra/railway.scheduler.toml | Autonomous scheduler and reconciliation loop |
| alpaca-mcp | Railway | infra/railway.mcp.toml | Internal official Alpaca MCP server |
| web | Vercel | Root directory web/ and infra/vercel.json | Next.js public application |

The api and scheduler use the image defined in infra/Dockerfile.agent. The
MCP service uses infra/Dockerfile.mcp. The MCP service must remain internal
and must not be exposed as a public endpoint.

## Paper-only requirements

Before deployment:

1. Confirm ALPACA_BASE_URL is exactly
   https://paper-api.alpaca.markets.
2. Use a dedicated Alpaca paper account for competition activity.
3. Run database migrations successfully.
4. Confirm the API reports healthy and paper_endpoint true.
5. Keep entry disabled until the operator has completed the runbook.

Do not deploy live brokerage credentials. The application contains multiple
paper-only checks, but deployment configuration must also enforce the same
boundary.

## Railway service configuration

Set the following variables on the api and scheduler services:

| Variable | Value or guidance |
| --- | --- |
| ALPACA_BASE_URL | https://paper-api.alpaca.markets |
| ALPACA_API_KEY | Alpaca paper key |
| ALPACA_SECRET_KEY | Alpaca paper secret |
| OPENAI_API_KEY | OpenAI API key |
| DATABASE_URL | Connection string from the Railway PostgreSQL service |
| LEXGUARD_ENVIRONMENT | development while rehearsing, competition for the final account |
| LEXGUARD_ENTRY_ENABLED | false by default; enable only on the scheduler after readiness checks |
| LEXGUARD_MCP_URL | http://alpaca-mcp.railway.internal:8010/mcp |
| LEXGUARD_OPTION_FEED | indicative or opra, with the choice disclosed |
| LEXGUARD_MAX_QUOTE_WIDTH | 0.40 unless the approved operating configuration requires another value |
| LEXGUARD_COMPETITION_BASELINE | 100000 for the competition account |
| LEXGUARD_UNDERLYING_ROTATION | SPY,QQQ,IWM,SPY |
| LEXGUARD_ALLOWED_SIDES | BOTH, LONG_ONLY, or SHORT_ONLY |
| LEXGUARD_MAX_ENTRIES_PER_DAY | 3 |
| LEXGUARD_FORECAST_ARTIFACT_PATH | artifacts/generated/forecast-SPY.json |
| LEXGUARD_FORECAST_ARTIFACT_PATH_QQQ | artifacts/generated/forecast-QQQ.json |
| LEXGUARD_FORECAST_ARTIFACT_PATH_IWM | artifacts/generated/forecast-IWM.json |
| LEXGUARD_ALLOWED_ORIGIN | Exact public Vercel origin |

Set LEXGUARD_OPERATOR_TOKEN on the api service to a long random secret.
Keep it out of logs and source control. It may also be present on the
scheduler service if the deployment platform shares environment settings,
but the web client must never receive it.

Set the following variables on the alpaca-mcp service:

~~~text
ALPACA_API_KEY=<Alpaca paper key>
ALPACA_SECRET_KEY=<Alpaca paper secret>
ALPACA_PAPER_TRADE=true
~~~

The scheduler configuration seeds risk state and forecast artifacts at boot.
The filesystem is ephemeral, so durable case state belongs in PostgreSQL and
runtime artifacts must be recreated safely on restart.

## Vercel web service

Configure:

- Root directory: web/
- Framework: Next.js
- Package manager: pnpm
- Configuration reference: infra/vercel.json
- NEXT_PUBLIC_API_BASE_URL: the public HTTPS origin of the Railway api service

The web build should fail when NEXT_PUBLIC_API_BASE_URL is missing. Never
place an Alpaca key, secret, operator token, or private account identifier in
any NEXT_PUBLIC_* variable.

## Deploy and verify

Run migrations before starting the API and scheduler. The provided Railway
files define the migration command and health check:

- API start: lexguard serve --host 0.0.0.0 --port 8000
- API health: GET /api/status
- Scheduler start: seed runtime artifacts, then lexguard scheduler --watch
- MCP start: alpaca-mcp-server --transport streamable-http --host 0.0.0.0 --port 8010

After deployment, verify:

1. GET the API /api/status endpoint and confirm HTTP 200 with healthy
   components.
2. GET /api/account and confirm paper_endpoint is true.
3. Check scheduler logs for off-hours SKIPPED or NO_WINDOW ticks.
4. Open the Vercel application and confirm it can read the API.
5. Test the operator pause control with the token and confirm the next
   scheduler tick reports entries disabled.
6. Keep entries disabled until the operator has completed the paper session
   checklist in docs/runbook.md.

## Operational notes

- Run one scheduler replica only. Multiple schedulers can create duplicate
  decision windows.
- Keep the MCP service internal.
- Treat Railway logs, database backups, and evidence exports as sensitive.
- Export redacted evidence only after reconciliation against Alpaca broker
  truth.
- A failed health check must stop the release or keep entries disabled. Do not
  replace a missing dependency with a fabricated zero or success value.
