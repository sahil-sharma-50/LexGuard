# LabLab submission draft - Lexguard

## Title

Lexguard: AI argues. Risk decides.

## Short description

A paper-only autonomous options agent that turns point-in-time Alpaca evidence
into a bounded four-leg trade certificate - or an inspectable abstention -
with a live command center showing its money, its arguments, and its stop-only
human controls.

## Long description

Lexguard evaluates SPY, QQQ, and IWM at four fixed intraday windows
(10:05, 11:35, 13:05, 14:20 ET), rotating the underlying across windows. All
market evidence flows through the official Alpaca MCP server and is frozen
into content-hashed snapshots. A calibrated forecast (fit on Alpaca 5-minute
bars) proposes only liquid, covered, equal-ratio four-leg condors with 1–3
DTE. An evidence-grounded AI catalyst advocate may choose a fixed scenario or
veto - citing only supplied Alpaca news IDs - but the deterministic judge
alone controls strikes, size, price, payoff, limits, and broker actions
($1,000/trade, $1,500/day, $4,000 drawdown halt, force-flat by 15:30 ET).
Execution is one atomic `mleg` order through the Alpaca Trading API with a
submission-anchored cancel ladder and broker-truth reconciliation. Each
decision becomes a replayable case file: evidence → argument → certificate →
order lifecycle → reconciled result. A human operator holds token-gated,
stop-only controls (pause, emergency stop, per-case veto) and can never
initiate a trade. The command center streams the agent's decisions live over
SSE beside the equity curve, positions, and orders.

## Technology tags

Alpaca Trading API, Alpaca MCP, Alpaca CLI, Python, FastAPI, Next.js,
PostgreSQL, OpenAI Responses API, options, paper trading.

## Links and evidence placeholders

- LabLab event: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon
- Public repository: `TO BE PROVIDED`
- Application URL: `TO BE PROVIDED`
- Competition paper account ID: `TO BE PROVIDED AFTER FRESH ACCOUNT GATE`
- Video: `TO BE RECORDED DURING A LIVE WINDOW`
- Slides: `docs/submission/slide-outline.md`
- One-page write-up: `docs/submission/one-page-writeup.md`

No performance number is included until it is backed by a reconciled paper
export from the competition account.
