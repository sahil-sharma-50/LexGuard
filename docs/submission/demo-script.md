# 3-minute demo script

Record during a live window (10:05 or 13:05 ET) with the Alpaca paper
dashboard side-by-side. Use only real case/order IDs from the competition
account.

00:00–00:15 - Thesis over the command center hero: intraday options decisions
fail when the AI invents contracts or risk. Here, **AI argues, risk decides**
- the model can only pick a scenario or veto; deterministic code certifies
and executes.

00:15–00:45 - Command center, MONEY zone: live equity curve, positions with
per-leg P&L, orders. Point at the drawdown gauge vs the $4,000 halt and the
$1,000/trade, $1,500/day caps.

00:45–01:30 - AGENT zone, live: the SSE decision ticker moves through
OBSERVED → FORECASTED → ARGUED → CERTIFIED → SUBMITTED → FILLED. Open the
case: hash-chained evidence, the LLM's verbatim argument with cited Alpaca
news IDs, the deterministic risk certificate. Split-screen the Alpaca
dashboard showing the same atomic 4-leg `mleg` order ID filling.

01:30–02:00 - CONTROLS zone: enter the operator token, pause the agent, show
the scheduler skipping entries on the next tick, resume. State that controls
are stop-only - a human can never initiate a trade. Show a refused case:
abstention (VETO / refusal codes) is autonomous behavior, not failure.

02:00–02:30 - Provenance: every data element badges its source - Alpaca MCP
tool for evidence, Alpaca CLI for research/forecast calibration, Trading API
order IDs for fills. Show the exported evidence bundle whose order IDs match
the submitted account.

02:30–03:00 - Results: P&L over the competition days with explicit provenance
labels (only reconciled paper activity), then close on the architecture
diagram: Trading API + MCP server + CLI, paper-only, fail-closed.
