# Contributing to Lexguard

Thank you for helping improve Lexguard. The project is deliberately
fail-closed, paper-only, and evidence-driven. Contributions should preserve
those properties while making the system easier to understand, test, and
operate.

## Before you start

1. Read README.md for the project model and local setup.
2. Read docs/runbook.md before touching paper-trading workflows.
3. Do not use live brokerage credentials or real capital.
4. Do not commit .env files, account identifiers, private exports, generated
   runtime artifacts, or dependency directories.

## Development workflow

Create a focused branch for each change. Keep unrelated cleanup out of feature
pull requests. If a change affects the risk boundary, broker adapter,
scheduler, public redaction, or Training Room isolation, explain the impact in
the pull request description.

Use the Docker workflow from README.md for the quickest complete local setup.
Native development is available on macOS, Linux, and WSL.

## Testing

Run the full offline verification before opening a pull request:

~~~bash
make verify
~~~

On Windows PowerShell:

~~~powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
~~~

For focused changes, also run the nearest test suite directly:

- Python: ruff, mypy, and pytest from the agent virtual environment
- Web: TypeScript checking, Vitest, and the relevant Playwright project

Keep network-backed smoke tests opt-in. Use only Alpaca paper credentials
when running them.

## Code and documentation expectations

- Prefer explicit, deterministic behavior over hidden defaults.
- Treat missing, stale, malformed, or contradictory data as a reason to stop.
- Keep public API projections redacted and free of private account data.
- Preserve the distinction between real paper operations and the synthetic
  browser-local Training Room.
- Update README.md or the relevant runbook when commands, environment
  variables, routes, or deployment behavior change.
- Include tests for behavior changes and comments for non-obvious safety
  decisions.
- Use plain, direct language in public documentation.

## Pull requests

A pull request should include:

- A short summary of the change and why it is needed
- The verification commands that were run
- Any known limitations or operator-owned follow-up
- Evidence that no credentials or private account data were added

Do not present simulated, historical, or incomplete results as live trading
performance. Every performance claim must point to a reconciled artifact.
