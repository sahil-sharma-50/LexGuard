#!/usr/bin/env bash
# Canonical offline verification for macOS/Linux (mirror of verify.ps1):
# agent lint + types + tests, then web fonts + lint + tests + build.
# Preserves the first failing exit code.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${REPO_ROOT}/agent/.venv/bin/python"
FIRST_FAILURE=0

# Prefer an npm-global pnpm over a corepack shim that needs network access.
NPM_GLOBAL_BIN="$(npm prefix -g 2>/dev/null)/bin"
if [ -x "${NPM_GLOBAL_BIN}/pnpm" ]; then
  PATH="${NPM_GLOBAL_BIN}:${PATH}"
fi

run_step() {
  local name="$1"
  shift
  echo "==> ${name}"
  "$@"
  local code=$?
  if [ "${code}" -ne 0 ] && [ "${FIRST_FAILURE}" -eq 0 ]; then
    FIRST_FAILURE="${code}"
    echo "FAILED (${code}): ${name}" >&2
  fi
  return 0
}

if [ ! -x "${PYTHON}" ]; then
  echo "agent venv missing: run 'uv venv agent/.venv && uv pip install -e agent[dev]'" >&2
  exit 1
fi

cd "${REPO_ROOT}/agent" || exit 1
run_step "agent: ruff" "${PYTHON}" -m ruff check src tests
run_step "agent: mypy" "${PYTHON}" -m mypy src
run_step "agent: pytest" "${PYTHON}" -m pytest -q

cd "${REPO_ROOT}/web" || exit 1
run_step "web: verify fonts" pnpm run verify:fonts
run_step "web: lint" pnpm run lint
run_step "web: unit tests" pnpm run test
run_step "web: production build" pnpm run build

if [ "${FIRST_FAILURE}" -ne 0 ]; then
  echo "verification failed with exit code ${FIRST_FAILURE}" >&2
  exit "${FIRST_FAILURE}"
fi
echo "verification passed"
