# Claim-to-evidence map

This map keeps public claims tied to a source and a reproducible command.
Replace PENDING LIVE RUNS only with reconciled evidence from the competition
paper account. If an artifact does not exist, remove the claim instead of
estimating it.

| Claim | Metric or value | Environment | Evidence source | Reproduction command |
| --- | --- | --- | --- | --- |
| Strategy return | PENDING LIVE RUNS | Competition paper | artifacts/paper-forward/evidence-*.json and reconciled performance series | python scripts/export_competition_evidence.py --environment competition |
| Maximum drawdown | PENDING LIVE RUNS | Competition paper | Persisted performance_snapshot series | agent/.venv/bin/lexguard daily-report --final |
| Autonomous lifecycle | PENDING LIVE RUNS | Competition paper | Case archive plus Alpaca order IDs in evidence bundle | agent/.venv/bin/lexguard export-evidence --case CASE_ID --environment competition |
| MCP integration | Read-only seven-tool evidence gateway | Code and live | agent/src/lexguard/adapters/alpaca_mcp.py and market_evidence artifacts | cd agent && LEXGUARD_RUN_ALPACA_SMOKE=1 .venv/bin/python -m pytest -m alpaca_smoke |
| CLI integration | Historical data and forecast calibration with provenance | Code and artifacts | agent/src/lexguard/research/cli.py and dataset manifests | cd agent && .venv/bin/lexguard-research fetch --help |
| Options execution | Atomic four-leg mleg orders and inverse closes | Code and live | agent/src/lexguard/adapters/alpaca_trading.py and evidence order IDs | cd agent && .venv/bin/python -m pytest tests/integration/test_execution.py |
| Risk gates | $1,000 trade, $1,500 daily, $4,000 drawdown, force-flat 15:30 ET | Code | agent/src/lexguard/domain/policy.py and agent/src/lexguard/services/judge.py | cd agent && .venv/bin/python -m pytest tests/unit/domain/test_policy.py |
| Stop-only controls | Pause, emergency stop, and case veto | Code | agent/src/lexguard/api/operator.py and scheduler entry gates | cd agent && .venv/bin/python -m pytest tests/contract/test_operator_api.py |
| Feed disclosure | Explicit indicative or opra provenance | Configuration and code | .env.example and quote feed fields in evidence | cd agent && .venv/bin/python -m pytest tests/contract/test_alpaca_mcp.py |
| Refusal behavior | Veto and refusal are autonomous outcomes | Live and replay | Refused case files with reason codes | cd web && pnpm playwright |

The evidence exporter omits credentials and account identifiers while retaining
order IDs as the join key judges can compare with the submitted account.
