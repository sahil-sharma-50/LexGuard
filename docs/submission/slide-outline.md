# Lexguard slide outline

1. **Problem** - Intraday options trading is a bounded decision problem, not
   an LLM guessing game. Letting a model invent contracts, prices, or risk is
   how agents blow up.
2. **Mechanism** - AI argues; the deterministic court decides. The model may
   only pick one of six scenarios or veto, citing supplied Alpaca news IDs.
3. **Decision architecture** - Alpaca MCP evidence (hash-frozen) → calibrated
   forecast (fit via Alpaca CLI data) → constrained AI scenario → candidate
   condors → deterministic judge → atomic Trading API execution →
   reconciliation. Four windows/day, SPY→QQQ→IWM rotation.
4. **Risk constitution** - exact payoff at every strike; $1,000 trade cap,
   $1,500 daily cap, $4,000 drawdown halt on a persisted equity peak;
   fresh-evidence and feed-provenance gates; no 0DTE, no overnight risk,
   force-flat 15:30 ET; certificate hash + expiry.
5. **Command center (live demo still)** - money (equity curve, positions,
   orders), agent decision stream over SSE with the verbatim LLM argument,
   stop-only operator controls (pause / emergency stop / veto).
6. **Execution proof** - one atomic four-leg `mleg` order ID traced from the
   case file to the Alpaca dashboard; bounded replace; submission-anchored
   cancel; broker-truth reconciliation; honest abstentions.
7. **Performance evidence** - reconciled paper-forward exports from the
   competition account only; every number carries its provenance label.
8. **Close** - Trading API + MCP server + CLI in one auditable loop;
   paper-only; inspectable case files judges can verify offline.
