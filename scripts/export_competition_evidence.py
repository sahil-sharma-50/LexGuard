"""Export a redacted, judge-verifiable evidence bundle for the paper account.

Pulls real orders (all statuses), positions, and an account snapshot from the
Alpaca paper Trading API through the project's PaperBroker, joins them with
the ledger's case index, and writes a timestamped JSON bundle. Credentials and
account identifiers never enter the file; order IDs do, because they are the
join key judges can verify against the submitted account's activity.

Run from the repository root after each market close:

    agent/.venv/bin/python scripts/export_competition_evidence.py \
        --environment development
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from lexguard.adapters.repository import CaseRepository  # noqa: E402
from lexguard.cli import _safe_cli_payload, build_broker  # noqa: E402


async def _broker_state() -> dict[str, object]:
    broker = build_broker()
    account = await broker.get_account()
    positions = await broker.get_positions()
    orders = await broker.get_orders()
    return {
        "account": {
            "status": account.status.upper(),
            "equity": str(account.equity),
            "last_equity": (
                str(account.last_equity) if account.last_equity is not None else None
            ),
            "daily_pnl": str(account.daily_pnl) if account.daily_pnl is not None else None,
            "competition_drawdown": (
                str(account.competition_drawdown)
                if account.competition_drawdown is not None
                else None
            ),
            "options_level": account.options_level,
            "paper_endpoint": account.base_url == "https://paper-api.alpaca.markets",
        },
        "orders": [
            {
                "order_id": order.order_id,
                "status": order.status,
                "filled_quantity": order.filled_quantity,
                "average_fill_price": (
                    str(order.average_fill_price)
                    if order.average_fill_price is not None
                    else None
                ),
                "client_order_id": order.client_order_id,
            }
            for order in orders
        ],
        "positions": [
            {
                "symbol": position.symbol,
                "quantity": position.quantity,
                "side": position.side,
                "unrealized_pnl": (
                    str(position.unrealized_pnl)
                    if position.unrealized_pnl is not None
                    else None
                ),
            }
            for position in positions
        ],
    }


def _ledger_state(environment: str) -> dict[str, object]:
    repository = CaseRepository(os.getenv("DATABASE_URL", "sqlite://"))
    cases: list[dict[str, object]] = []
    performance: list[dict[str, object]] = []
    try:
        records, _ = repository.list_ledger_cases(0, 1000)
        for record in records:
            if record.decision_window == "SYSTEM":
                continue
            cases.append(
                {
                    "case_id": str(record.case_id),
                    "trading_date": str(record.trading_date),
                    "decision_window": record.decision_window,
                    "state": record.state,
                    "underlying": record.underlying,
                    "artifacts": _safe_cli_payload(
                        {
                            name: payload
                            for name, payload in record.artifacts.items()
                            if name
                            in {
                                "trade_certificate",
                                "refusal_record",
                                "halt_record",
                                "catalyst_assessment",
                            }
                        }
                    ),
                }
            )
        for payload, content_hash, created_at in repository.artifacts_by_type(
            "performance_snapshot", limit=2000
        ):
            performance.append(
                {
                    "recorded_at": str(payload.get("recorded_at") or created_at.isoformat()),
                    "content_hash": content_hash,
                    "metrics": _safe_cli_payload(payload.get("metrics", {})),
                }
            )
    except Exception as exc:  # noqa: BLE001 - an unavailable ledger is reported, not faked
        return {"cases": [], "performance": [], "ledger_unavailable": str(type(exc).__name__)}
    return {"cases": cases, "performance": performance, "ledger_unavailable": None}


def export_evidence(environment: str, output: Path) -> Path:
    broker_state = asyncio.run(_broker_state())
    ledger_state = _ledger_state(environment)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "environment": environment,
                "created_at": datetime.now(UTC).isoformat(),
                "paper_only": True,
                "broker": broker_state,
                "ledger": ledger_state,
                "redaction": "credentials and account IDs omitted; order IDs retained for judge verification",
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("development", "competition"), required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Defaults to artifacts/paper-forward/evidence-<UTC timestamp>.json",
    )
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or Path("artifacts/paper-forward") / f"evidence-{stamp}.json"
    print(export_evidence(args.environment, output))


if __name__ == "__main__":
    main()
