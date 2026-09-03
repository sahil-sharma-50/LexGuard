# Lexguard

> Submission draft. Add account details and performance only after the final
> paper-forward evidence has been reconciled.

## One-line summary

Lexguard is a paper-only autonomous options agent where AI argues, deterministic
risk code decides, and every outcome is recorded as a replayable case file.

## Problem

Intraday options decisions become difficult to audit when a language model can
invent contracts, prices, or risk. Lexguard separates interpretation from
authority. The model can explain a supplied market scenario or veto a case.
Deterministic code controls candidate generation, payoff, risk certification,
order construction, and reconciliation. An abstention is a successful safety
decision, not an empty result.

## Decision loop

At 10:05, 11:35, 13:05, and 14:20 ET, the agent reads completed five-minute
bars, near-the-money option chains, account state, positions, orders, and news
through the official Alpaca MCP server. It freezes that input into a
content-hashed evidence snapshot. A calibrated forecast estimates the signed
move to 15:30 ET. Deterministic code generates only covered, equal-ratio,
same-expiration four-leg condor structures with 1 to 3 DTE, rotating the
underlying from SPY to QQQ to IWM across windows.

The OpenAI catalyst component receives only the case evidence and may select
one fixed scenario: BASE, VOL_UP, VOL_DOWN, LEFT_TAIL, RIGHT_TAIL, or VETO. It
must cite supplied Alpaca news IDs. Invalid, stale, unavailable, or uncited
output becomes VETO. The model cannot choose a symbol, strike, size, limit
price, or broker action.

## Risk and execution

The deterministic judge computes exact multi-leg payoff and rejects candidates
that exceed the $1,000 trade-loss limit, $1,500 daily-loss limit, or $4,000
competition drawdown halt. It also enforces fresh evidence, quote provenance,
account readiness, fixed windows, re-entry limits, a daily entry cap, one open
structure, no 0DTE, no overnight risk, certificate integrity, and certificate
expiry.

Execution uses one atomic paper mleg limit order through the Alpaca Trading API.
The order has a deterministic client order ID, a bounded replacement path, a
submission-anchored cancel ladder, and broker-truth reconciliation after every
mutation. Positions are force-flat by 15:30 ET. An operator can pause, resume,
emergency-stop, or veto a pending case through token-gated controls, but cannot
initiate a trade.

## Technology

- Alpaca Trading API through alpaca-py for paper execution and broker truth
- Official Alpaca MCP server for the read-only market evidence boundary
- Alpaca CLI for reproducible historical data and forecast calibration
- OpenAI Responses API for the bounded catalyst argument
- Python, FastAPI, PostgreSQL, SQLAlchemy, and a watch-mode scheduler
- Next.js command center, public case archive, and browser-local Training Room

## Evidence and validation

The repository contains deterministic fixtures, public replay surfaces, and an
offline test suite covering payoff, candidate generation, judging, execution
failure drills, reconciliation, control authentication, and API redaction.
Live account results are not claimed until reconciled artifacts exist.

The selected options feed are explicit and must be disclosed with the final
evidence: opra with the appropriate subscription, or Alpaca's indicative
derived feed.

## Final submission fields

- Competition paper account ID: to be added after the fresh-account gate
- Final paper P&L: to be reported from reconciled Alpaca paper activity
- Public repository: to be added
- Application URL: to be added
- Video and slides: to be added
