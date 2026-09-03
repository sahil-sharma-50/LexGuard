"""Command-center surface: live broker projections and stop-only controls.

Two invariants hold everywhere in this module:

- No HTTP route can submit, replace, or cancel a broker order. The GET routes
  are read-only broker projections; the POST controls write ledger artifacts
  that the scheduler worker reads on its next tick.
- A human can only stop the agent (pause, emergency stop, per-case veto).
  The operator can never initiate or modify a trade.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException

from lexguard.adapters.alpaca_trading import PaperBroker
from lexguard.adapters.repository import CaseRepository
from lexguard.settings import Settings

_NEW_YORK = ZoneInfo("America/New_York")

BrokerFactory = Callable[[], Any]


def default_broker_factory() -> PaperBroker:
    settings = Settings().paper_only()  # type: ignore[call-arg, operator]
    return PaperBroker(
        settings.alpaca_api_key.get_secret_value(),
        settings.alpaca_secret_key.get_secret_value(),
        base_url=str(settings.alpaca_base_url),
    )


def _require_operator(token: str | None) -> None:
    expected = os.getenv("LEXGUARD_OPERATOR_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="operator controls are not configured")
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="operator token is invalid")


def build_operator_router(
    repository: CaseRepository,
    *,
    broker_factory: BrokerFactory = default_broker_factory,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    broker_cache: dict[str, Any] = {}

    def _broker() -> Any:
        if "broker" not in broker_cache:
            try:
                broker_cache["broker"] = broker_factory()
            except Exception as exc:
                raise HTTPException(
                    status_code=503, detail="paper broker is unavailable"
                ) from exc
        return broker_cache["broker"]

    @router.get("/account")
    async def account() -> dict[str, Any]:
        try:
            row = await _broker().get_account()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail="broker account read failed") from exc
        return {
            "status": row.status.upper(),
            "equity": str(row.equity),
            "last_equity": str(row.last_equity) if row.last_equity is not None else None,
            "daily_pnl": str(row.daily_pnl) if row.daily_pnl is not None else None,
            "competition_drawdown": (
                str(row.competition_drawdown)
                if row.competition_drawdown is not None
                else None
            ),
            "buying_power": str(row.buying_power) if row.buying_power is not None else None,
            "options_level": row.options_level,
            "paper_endpoint": row.base_url == "https://paper-api.alpaca.markets",
        }

    @router.get("/positions")
    async def positions() -> dict[str, Any]:
        try:
            rows = await _broker().get_positions()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail="broker positions read failed") from exc
        return {
            "positions": [
                {
                    "symbol": row.symbol,
                    "quantity": row.quantity,
                    "side": row.side,
                    "unrealized_pnl": (
                        str(row.unrealized_pnl) if row.unrealized_pnl is not None else None
                    ),
                }
                for row in rows
            ]
        }

    @router.get("/orders")
    async def orders() -> dict[str, Any]:
        try:
            rows = await _broker().get_orders()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail="broker orders read failed") from exc
        return {
            "orders": [
                {
                    "order_id": row.order_id,
                    "status": row.status,
                    "filled_quantity": row.filled_quantity,
                    "average_fill_price": (
                        str(row.average_fill_price)
                        if row.average_fill_price is not None
                        else None
                    ),
                    "client_order_id": row.client_order_id,
                }
                for row in rows
            ]
        }

    @router.get("/performance/history")
    def performance_history(limit: int = 500) -> dict[str, Any]:
        snapshots = repository.artifacts_by_type(
            "performance_snapshot", limit=max(1, min(limit, 2000))
        )
        points = []
        for payload, _, created_at in snapshots:
            metrics = payload.get("metrics", {})
            if not isinstance(metrics, dict):
                continue
            points.append(
                {
                    "recorded_at": str(payload.get("recorded_at") or created_at.isoformat()),
                    "equity": metrics.get("equity"),
                    "daily_pnl": metrics.get("daily_pnl"),
                    "competition_drawdown": metrics.get("competition_drawdown"),
                }
            )
        return {"points": points}

    def _write_control(
        *, entries_enabled: bool, stop_active: bool, actor: str, action: str
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        trading_date = now.astimezone(_NEW_YORK).date()
        control_payload = {
            "entries_enabled": entries_enabled,
            "action": action,
            "actor": actor,
            "updated_at": now.isoformat(),
        }
        stop_payload = {
            "active": stop_active,
            "action": action,
            "actor": actor,
            "updated_at": now.isoformat(),
        }
        try:
            repository.save_runtime_artifact(
                trading_date, "entry_control", control_payload, now=now
            )
            repository.save_runtime_artifact(
                trading_date, "operator_stop", stop_payload, now=now
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="control ledger write failed") from exc
        return {
            "action": action,
            "entries_enabled": entries_enabled,
            "emergency_stop": stop_active,
            "effective": "next scheduler tick",
        }

    @router.post("/controls/pause")
    def pause(x_operator_token: str | None = Header(default=None)) -> dict[str, Any]:
        _require_operator(x_operator_token)
        return _write_control(
            entries_enabled=False, stop_active=False, actor="operator", action="PAUSE"
        )

    @router.post("/controls/resume")
    def resume(x_operator_token: str | None = Header(default=None)) -> dict[str, Any]:
        _require_operator(x_operator_token)
        return _write_control(
            entries_enabled=True, stop_active=False, actor="operator", action="RESUME"
        )

    @router.post("/controls/emergency-stop")
    def emergency_stop(
        x_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_operator(x_operator_token)
        return _write_control(
            entries_enabled=False,
            stop_active=True,
            actor="operator",
            action="EMERGENCY_STOP",
        )

    @router.post("/cases/{case_id}/veto")
    def veto(
        case_id: UUID, x_operator_token: str | None = Header(default=None)
    ) -> dict[str, Any]:
        _require_operator(x_operator_token)
        record = repository.ledger_case(case_id)
        if record is None or record.decision_window == "SYSTEM":
            raise HTTPException(status_code=404, detail="case not found")
        if "trade_certificate" not in record.artifacts:
            raise HTTPException(status_code=409, detail="case has no pending certificate")
        now = datetime.now(UTC)
        try:
            repository.save_artifact(
                case_id,
                "operator_veto",
                {"actor": "operator", "created_at": now.isoformat()},
                created_at=now,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="veto ledger write failed") from exc
        return {"case_id": str(case_id), "vetoed": True, "effective": "next scheduler tick"}

    return router
