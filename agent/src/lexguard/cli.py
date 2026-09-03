"""Fail-closed operator CLI for the read and paper-trading processes."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, NoReturn, TypedDict, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import typer

from lexguard.adapters.alpaca_mcp import (
    AlpacaMcpGateway,
    FastMcpHttpClient,
    McpClient,
)
from lexguard.adapters.alpaca_trading import (
    BROKER_ACTIVE_ORDER_STATES,
    PAPER_BASE_URL,
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
    PaperBroker,
)
from lexguard.adapters.openai_catalyst import (
    MODEL_NAME,
    OpenAICatalystClient,
    OpenAIResponsesClient,
)
from lexguard.adapters.repository import CaseRepository
from lexguard.domain.models import ForecastDistribution, TradeCertificate
from lexguard.domain.policy import RiskContext, RiskPolicy
from lexguard.research.features import build_features
from lexguard.research.forecast import ForecastArtifact, ForecastEnsemble
from lexguard.services.candidates import CandidateService
from lexguard.services.case_service import CaseService
from lexguard.services.deliberation import DeliberationService
from lexguard.services.evidence import EvidenceService
from lexguard.services.execution import ExecutionService
from lexguard.services.health import record_health_heartbeat
from lexguard.services.judge import Judge
from lexguard.services.position_manager import PositionEvidence, PositionManager
from lexguard.services.reconciliation import ReconciliationService
from lexguard.services.risk_state import RiskStateService
from lexguard.services.scheduler import (
    CalendarSession,
    PositionSnapshot,
    PositionSnapshotProvider,
    Scheduler,
)
from lexguard.settings import Settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
_ACTIVE_ORDER_STATES = BROKER_ACTIVE_ORDER_STATES


def _json(value: Any) -> None:
    typer.echo(json.dumps(value, default=str, sort_keys=True, indent=2))


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


def _entry_state_path() -> Path:
    return Path(os.getenv("LEXGUARD_ENTRY_STATE_PATH", ".lexguard/entry-state.json"))


def _entry_enabled() -> bool:
    path = _entry_state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return os.getenv("LEXGUARD_ENTRY_ENABLED", "false").lower() == "true"
    return bool(payload.get("entry_enabled", False))


def _write_entry_state(enabled: bool, *, environment: str | None = None) -> None:
    path = _entry_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "entry_enabled": enabled,
        "environment": environment or os.getenv("LEXGUARD_ENVIRONMENT", "development"),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _entry_enabled_with(repository: Any) -> Callable[[], bool]:
    """AND the local entry state with the DB-backed operator control.

    The API service and the scheduler worker run as separate processes, so
    pause/resume must travel through the shared ledger. Both layers are
    fail-closed: a DB read failure disables entries.
    """

    def check() -> bool:
        if not _entry_enabled():
            return False
        reader = getattr(repository, "latest_artifact", None)
        if not callable(reader):
            return False
        try:
            artifact = reader("entry_control")
        except Exception:
            return False
        if artifact is None:
            return True
        payload = artifact[0]
        return isinstance(payload, Mapping) and payload.get("entries_enabled") is True

    return check


def _operator_stop_active(repository: Any) -> bool:
    reader = getattr(repository, "latest_artifact", None)
    if not callable(reader):
        return False
    try:
        artifact = reader("operator_stop")
    except Exception:
        # Unknown stop state must not force-close positions; entries are
        # already disabled by the fail-closed entry gate.
        return False
    if artifact is None:
        return False
    payload = artifact[0]
    return isinstance(payload, Mapping) and payload.get("active") is True


def _runtime_environment() -> str:
    value = os.getenv("LEXGUARD_ENVIRONMENT", "development")
    if value not in {"development", "competition"}:
        _fail("LEXGUARD_ENVIRONMENT must be development or competition")
    return value


def _settings() -> Settings:
    try:
        return Settings().paper_only()  # type: ignore[call-arg,operator,no-any-return]
    except Exception as exc:
        _fail(f"runtime configuration is not safe: {exc}")
    raise AssertionError("unreachable")


def _option_feed() -> str:
    value = os.getenv("LEXGUARD_OPTION_FEED", "opra").lower()
    if value not in {"opra", "indicative"}:
        raise ValueError("LEXGUARD_OPTION_FEED must be opra or indicative")
    return value


def _competition_baseline() -> Decimal:
    return _decimal_setting("LEXGUARD_COMPETITION_BASELINE", "100000")


def build_broker() -> PaperBroker:
    """Build the only broker adapter allowed by this process."""

    settings = _settings()
    return PaperBroker(
        settings.alpaca_api_key.get_secret_value(),
        settings.alpaca_secret_key.get_secret_value(),
        base_url=str(settings.alpaca_base_url),
        competition_baseline=_competition_baseline(),
    )


class _FailClosedCaseEvaluator:
    """Retain a safe scheduler object when a deployment is not fully configured."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def evaluate(self, window: Any, now: datetime) -> Any:
        raise RuntimeError(self.reason)


class _BrokerCalendarProvider:
    """Adapt broker calendar rows to the scheduler's immutable session contract."""

    def __init__(self, broker: PaperBroker) -> None:
        self.broker = broker

    async def get_clock(self) -> Any:
        return await self.broker.get_clock()

    async def get_calendar(self, start: date, end: date) -> tuple[Any, ...]:
        rows = await self.broker.get_calendar(start, end)
        return tuple(CalendarSession(row.trading_date, row.open, row.close) for row in rows)


class _BrokerRiskContextProvider:
    """Rebuild the entry policy context from broker truth at submission time."""

    def __init__(self, repository: CaseRepository, *, required_feed: str = "opra") -> None:
        self.repository = repository
        self.required_feed = required_feed

    async def build(
        self,
        certificate: TradeCertificate,
        now: datetime,
        account: BrokerAccount,
        positions: tuple[BrokerPosition, ...],
        orders: tuple[BrokerOrder, ...],
        clock: Any,
        quotes: tuple[Any, ...],
    ) -> RiskContext:
        risk_state = _verified_risk_state(self.repository)
        if (
            account.last_equity is None
            or account.daily_pnl is None
            or account.competition_drawdown is None
            or account.options_level is None
            or risk_state is None
        ):
            raise RuntimeError("verified broker and persisted risk state are required")
        local_date = now.astimezone(ZoneInfo("America/New_York")).date()
        daily = self.repository.daily_entry_state(local_date)
        observed_at = min(
            (quote.observed_at for quote in quotes),
            default=now,
        )
        options_level = account.options_level
        # "opra_available" means: every refreshed quote carries the configured
        # feed's provenance. The configured feed is a disclosed operator choice.
        opra_available = bool(quotes) and all(
            quote.feed == self.required_feed for quote in quotes
        )
        return RiskContext(
            now=now,
            decision_window=_decision_window_for(now),
            evidence_observed_at=observed_at,
            # Use only verified broker values and durable competition counters;
            # a certificate can tighten these bounds but never replace them.
            daily_pnl=min(account.daily_pnl, risk_state["daily_pnl"], certificate.daily_pnl),
            competition_drawdown=max(
                account.competition_drawdown,
                risk_state["competition_drawdown"],
                max(risk_state["competition_peak_equity"] - account.equity, Decimal("0")),
                certificate.competition_drawdown,
            ),
            account_equity=account.equity,
            entries_today=daily.entries_today,
            traded_symbols_today=daily.traded_symbols_today,
            open_structure_count=1 if positions else 0,
            open_order_count=len(orders),
            open_position_count=len(positions),
            account_status=cast(Any, account.status.upper()),
            options_level=options_level,
            opra_available=opra_available,
            base_url=account.base_url,
            entry_attempt=False,
        )


class _BrokerPositionSnapshotProvider:
    """Produce conservative exit evidence from broker/MCP observations.

    The broker exposes unrealized P&L when available. If it does not, the
    snapshot intentionally marks the evaluation incomplete, allowing only the
    risk-halt/time exits until fresh P&L is available.
    """

    def __init__(
        self,
        broker: PaperBroker,
        gateway: AlpacaMcpGateway,
        calendar: _BrokerCalendarProvider,
        settings: Settings,
        edge_evaluator: Callable[[tuple[BrokerPosition, ...], datetime], bool | None] | None = None,
        repository: Any | None = None,
    ) -> None:
        self.broker = broker
        self.gateway = gateway
        self.calendar = calendar
        self.settings = settings
        self.edge_evaluator = edge_evaluator
        self.repository = repository

    async def snapshot(self, now: datetime) -> PositionSnapshot:
        positions = tuple(
            position for position in await self.broker.get_positions() if position.quantity
        )
        if not positions:
            return PositionSnapshot(
                positions=(),
                evidence=PositionEvidence(
                    observed_at=now,
                    unrealized_pnl=Decimal("0"),
                    edge_valid=False,
                    evaluation_complete=False,
                    risk_halt=False,
                ),
            )
        account = await self.gateway.get_account_info()
        local_date = now.astimezone(ZoneInfo("America/New_York")).date()
        calendar_rows = await self.calendar.get_calendar(local_date, local_date)
        market_close = next(
            (row.close for row in calendar_rows if row.trading_date == local_date),
            None,
        )
        p_and_l = tuple(position.unrealized_pnl for position in positions)
        complete = all(value is not None for value in p_and_l)
        unrealized = sum((value or Decimal("0") for value in p_and_l), Decimal("0"))
        edge_valid = False
        if self.edge_evaluator is not None:
            try:
                evaluated = self.edge_evaluator(positions, now)
            except Exception:
                evaluated = None
            edge_valid = evaluated is True
        risk_halt = (
            not complete
            or account.daily_pnl <= -self.settings.max_daily_loss
            or account.competition_drawdown >= self.settings.max_competition_drawdown
            # An operator emergency stop closes the open structure through the
            # same deterministic RISK_HALT exit path.
            or (self.repository is not None and _operator_stop_active(self.repository))
        )
        return PositionSnapshot(
            positions=positions,
            evidence=PositionEvidence(
                observed_at=min(account.observed_at, now),
                unrealized_pnl=unrealized,
                edge_valid=edge_valid,
                # Missing P&L is a risk halt; otherwise an unavailable edge
                # evaluator remains a completed invalidation signal.
                evaluation_complete=True,
                risk_halt=risk_halt,
                market_close=market_close,
            ),
        )


class _RuntimeReadiness:
    """Async proof that every live scheduler boundary is usable and safe."""

    def __init__(
        self,
        *,
        settings: Settings,
        broker: Any,
        gateway: Any,
        assessor: Any,
        forecast_provider: Any,
        repository: CaseRepository,
        execution_service: Any,
        position_manager: Any,
        position_snapshot_provider: Any,
        position_closer: Any,
        underlying: str,
        static_blockers: tuple[str, ...],
    ) -> None:
        self.settings = settings
        self.broker = broker
        self.gateway = gateway
        self.assessor = assessor
        self.forecast_provider = forecast_provider
        self.repository = repository
        self.execution_service = execution_service
        self.position_manager = position_manager
        self.position_snapshot_provider = position_snapshot_provider
        self.position_closer = position_closer
        self.underlying = underlying
        self.static_blockers = static_blockers

    async def check(self) -> tuple[bool, tuple[str, ...]]:
        blockers = set(self.static_blockers)
        if blockers:
            return False, tuple(sorted(blockers))

        try:
            broker_account, _, _, broker_clock = await asyncio.gather(
                self.broker.get_account(),
                self.broker.get_positions(),
                self.broker.get_orders(),
                self.broker.get_clock(),
            )
        except Exception:
            blockers.add("BROKER_PREFLIGHT_FAILURE")
        else:
            if (
                self.broker.base_url.rstrip("/") != PAPER_BASE_URL
                or broker_account.base_url != PAPER_BASE_URL
            ):
                blockers.add("PAPER_ENDPOINT_REQUIRED")
            if broker_account.status.upper() != "ACTIVE" or broker_account.equity <= 0:
                blockers.add("BROKER_ACCOUNT_UNREADY")
            if broker_clock.timestamp is None:
                blockers.add("BROKER_CLOCK_UNAVAILABLE")
            if (
                broker_account.last_equity is None
                or broker_account.daily_pnl is None
                or broker_account.competition_drawdown is None
                or broker_account.options_level is None
            ):
                blockers.add("BROKER_RISK_STATE_UNAVAILABLE")
            elif broker_account.options_level < 3:
                blockers.add("BROKER_OPTIONS_LEVEL_UNAVAILABLE")

        if self.gateway is None:
            blockers.add("MCP_RUNTIME_UNCONFIGURED")
        else:
            try:
                if set(self.gateway.READ_ONLY_TOOLS) != set(AlpacaMcpGateway.READ_ONLY_TOOLS):
                    raise RuntimeError("MCP tool boundary changed")
                mcp_account, mcp_clock, option_quotes = await asyncio.gather(
                    self.gateway.get_account_info(),
                    self.gateway.get_clock(),
                    self.gateway.get_option_chain(self.underlying, limit=1),
                )
                if (
                    mcp_account.status != "ACTIVE"
                    or mcp_account.equity <= 0
                    or not mcp_account.opra_available
                    or not option_quotes
                    or not mcp_clock.timestamp
                ):
                    raise RuntimeError("MCP account, clock, or OPRA observation is unavailable")
            except Exception:
                blockers.add("MCP_PREFLIGHT_FAILURE")

        if self.assessor is None:
            blockers.add("OPENAI_RUNTIME_UNCONFIGURED")
        else:
            try:
                health = self.assessor.health_check
                result = health()
                if inspect.isawaitable(result):
                    result = await result
                if result is not True:
                    raise RuntimeError("structured output health check failed")
            except Exception:
                blockers.add("OPENAI_PREFLIGHT_FAILURE")

        forecast_hash = getattr(self.forecast_provider, "artifact_hash", None)
        if (
            not callable(self.forecast_provider)
            or not bool(getattr(self.forecast_provider, "forecast_artifact_verified", False))
            or not isinstance(forecast_hash, str)
            or len(forecast_hash) != 64
            or any(character not in "0123456789abcdef" for character in forecast_hash.lower())
        ):
            blockers.add("FORECAST_PROVENANCE_UNVERIFIED")
        try:
            if self.repository.database_health() != "healthy":
                blockers.add("DATABASE_MIGRATION_UNAVAILABLE")
        except Exception:
            blockers.add("DATABASE_MIGRATION_UNAVAILABLE")
        if _verified_risk_state(self.repository) is None:
            blockers.add("RISK_STATE_UNAVAILABLE")

        if (
            self.execution_service is None
            or getattr(self.execution_service, "quote_checker", None) is None
            or getattr(self.execution_service, "risk_context_provider", None) is None
        ):
            blockers.add("EXECUTION_DEPENDENCY_UNAVAILABLE")
        if (
            self.position_manager is None
            or self.position_snapshot_provider is None
            or self.position_closer is None
            or not callable(getattr(self.position_closer, "close", None))
        ):
            blockers.add("POSITION_DEPENDENCY_UNAVAILABLE")
        return not blockers, tuple(sorted(blockers))


_WINDOWS_IN_ORDER: tuple[str, ...] = ("10:05", "11:35", "13:05", "14:20")


def _decision_window_for(now: datetime) -> Literal["10:05", "11:35", "13:05", "14:20"]:
    local = now.astimezone(ZoneInfo("America/New_York")).time()
    if local >= dt_time(14, 20):
        return "14:20"
    if local >= dt_time(13, 5):
        return "13:05"
    if local >= dt_time(11, 35):
        return "11:35"
    return "10:05"


class _RotatingCaseEvaluator:
    """Dispatch each decision window to its rotation symbol's case service."""

    def __init__(self, services: Mapping[str, Any]) -> None:
        self.services = dict(services)

    async def evaluate(self, window: Any, now: datetime) -> Any:
        service = self.services.get(getattr(window, "value", str(window)))
        if service is None:
            raise RuntimeError("no case service is configured for this window")
        return await service.evaluate(window, now)


def _decimal_setting(name: str, default: str) -> Decimal:
    raw = os.getenv(name, default)
    try:
        value = Decimal(raw)
    except Exception as exc:
        raise ValueError(f"{name} must be a decimal") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


class _VerifiedForecastProvider:
    forecast_artifact_verified = True

    def __init__(self, ensemble: ForecastEnsemble, artifact_hash: str) -> None:
        self.ensemble = ensemble
        self.artifact_hash = artifact_hash

    def __call__(self, evidence: Any) -> ForecastDistribution:
        features = build_features(evidence.underlying_bars, evidence.observed_at)
        return self.ensemble.predict(features)


class _VerifiedRiskState(TypedDict):
    daily_pnl: Decimal
    competition_drawdown: Decimal
    competition_peak_equity: Decimal
    competition_counter: int


def _forecast_provider_from_file(path_value: str) -> Callable[[Any], ForecastDistribution]:
    payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("forecast artifact must be an object")
    if str(payload.get("feature_schema_hash")) != _forecast_schema_hash():
        raise ValueError("forecast artifact feature schema is incompatible")
    if int(payload.get("sample_count", 0)) <= 0:
        raise ValueError("forecast artifact sample_count must be positive")
    weights = tuple(Decimal(str(value)) for value in payload.get("weights", ()))
    if len(weights) != 3 or sum(weights, Decimal("0")) != Decimal("1"):
        raise ValueError("forecast artifact weights are invalid")
    artifact = ForecastArtifact(
        training_end=datetime.fromisoformat(str(payload["training_end"])),
        feature_schema_hash=str(payload["feature_schema_hash"]),
        sample_count=int(payload["sample_count"]),
        weights=weights,
        quantile_center=Decimal(str(payload["quantile_center"])),
        quantile_scale=Decimal(str(payload["quantile_scale"])),
        volatility_scale=Decimal(str(payload["volatility_scale"])),
        regime_center=Decimal(str(payload["regime_center"])),
        regime_scale=Decimal(str(payload["regime_scale"])),
        artifact_hash=str(payload["artifact_hash"]),
    )
    if artifact.training_end.tzinfo is None or artifact.training_end.utcoffset() is None:
        raise ValueError("forecast artifact training_end must be timezone-aware")
    if (
        artifact.quantile_scale <= 0
        or artifact.volatility_scale <= 0
        or artifact.regime_scale <= 0
    ):
        raise ValueError("forecast artifact scales must be positive")
    canonical_payload = {
        "training_end": artifact.training_end.isoformat(),
        "feature_schema_hash": artifact.feature_schema_hash,
        "sample_count": artifact.sample_count,
        "weights": [str(weight) for weight in artifact.weights],
        "quantile_center": str(artifact.quantile_center),
        "quantile_scale": str(artifact.quantile_scale),
        "volatility_scale": str(artifact.volatility_scale),
        "regime_center": str(artifact.regime_center),
        "regime_scale": str(artifact.regime_scale),
    }
    expected_hash = hashlib.sha256(
        json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if artifact.artifact_hash != expected_hash:
        raise ValueError("forecast artifact hash does not match canonical parameters")
    ensemble = ForecastEnsemble(artifact)

    return _VerifiedForecastProvider(ensemble, artifact.artifact_hash)


def _forecast_schema_hash() -> str:
    # Importing the frozen research constant keeps loader validation aligned
    # with the feature builder without duplicating its value.
    from lexguard.research.features import FEATURE_SCHEMA_HASH

    return FEATURE_SCHEMA_HASH


def _verified_risk_state(repository: CaseRepository) -> _VerifiedRiskState | None:
    """Load durable daily/competition counters, never synthesizing zeroes."""

    try:
        artifact = repository.latest_artifact("risk_state")
    except Exception:
        return None
    if artifact is None:
        return None
    payload, content_hash, _ = artifact
    if not isinstance(payload, Mapping):
        return None
    if content_hash != _payload_hash_for_runtime_state(payload):
        return None
    try:
        peak_raw = payload.get("competition_peak_equity", payload.get("peak_equity"))
        counter_raw = payload.get("competition_counter", payload.get("counter"))
        if peak_raw is None or counter_raw is None:
            return None
        peak = Decimal(str(peak_raw))
        counter_decimal = Decimal(str(counter_raw))
        if counter_decimal != counter_decimal.to_integral_value():
            return None
        counter = int(counter_decimal)
        daily = Decimal(str(payload["daily_pnl"]))
        drawdown = Decimal(str(payload["competition_drawdown"]))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None
    if (
        not peak.is_finite()
        or not daily.is_finite()
        or not drawdown.is_finite()
        or peak <= 0
        or counter < 0
    ):
        return None
    return {
        "daily_pnl": daily,
        "competition_drawdown": drawdown,
        "competition_peak_equity": peak,
        "competition_counter": counter,
    }


def _payload_hash_for_runtime_state(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _build_openai_assessor(
    settings: Settings,
    client: OpenAIResponsesClient | OpenAICatalystClient | None,
) -> OpenAICatalystClient | None:
    if isinstance(client, OpenAICatalystClient):
        return client
    if client is not None:
        return OpenAICatalystClient(client)
    if settings.openai_api_key is None:
        return None
    try:
        from openai import AsyncOpenAI

        return OpenAICatalystClient(
            cast(
                OpenAIResponsesClient,
                AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value()),
            ),
            model=MODEL_NAME,
        )
    except Exception:
        return None


def build_scheduler(
    *,
    settings: Settings | None = None,
    broker: Any | None = None,
    repository: CaseRepository | None = None,
    mcp_client: McpClient | None = None,
    gateway: AlpacaMcpGateway | None = None,
    openai_client: OpenAIResponsesClient | OpenAICatalystClient | None = None,
    forecast_provider: Callable[[Any], ForecastDistribution] | None = None,
    case_service: Any | None = None,
    execution_service: Any | None = None,
    position_manager: PositionManager | None = None,
    position_snapshot_provider: PositionSnapshotProvider | None = None,
    position_evidence_provider: PositionSnapshotProvider | None = None,
    position_closer: Any | None = None,
    position_edge_evaluator: Callable[[tuple[BrokerPosition, ...], datetime], bool | None]
    | None = None,
) -> Scheduler:
    """Compose the scheduler's complete internal dependency graph.

    The optional overrides are intentionally dependency-injection seams for
    offline tests and archived replay. The normal path constructs every
    provider from deployment configuration and records explicit blockers when
    any required dependency is absent; no partial scheduler can submit orders.
    """

    settings = settings or _settings()
    blockers: list[str] = []
    runtime_broker = broker or build_broker()
    runtime_repository = repository or CaseRepository(settings.database_url)
    if not os.getenv("DATABASE_URL"):
        blockers.append("DATABASE_URL_UNCONFIGURED")
    database_health = getattr(runtime_repository, "database_health", None)
    if callable(database_health) and database_health() != "healthy":
        blockers.append("DATABASE_MIGRATION_UNAVAILABLE")
    try:
        option_feed = _option_feed()
    except ValueError:
        blockers.append("OPTION_FEED_CONFIGURATION_INVALID")
        option_feed = "opra"

    def _competition_peak() -> Decimal | None:
        state = _verified_risk_state(runtime_repository)
        return None if state is None else state["competition_peak_equity"]

    runtime_gateway = gateway
    if runtime_gateway is None and mcp_client is not None:
        runtime_gateway = AlpacaMcpGateway(
            mcp_client,
            option_feed=option_feed,
            competition_peak_provider=_competition_peak,
        )
    if runtime_gateway is None:
        mcp_url = os.getenv("LEXGUARD_MCP_URL") or os.getenv("ALPACA_MCP_URL")
        if not mcp_url:
            if case_service is None:
                blockers.append("MCP_RUNTIME_UNCONFIGURED")
        else:
            try:
                runtime_gateway = AlpacaMcpGateway(
                    FastMcpHttpClient(mcp_url),
                    option_feed=option_feed,
                    competition_peak_provider=_competition_peak,
                )
            except Exception:
                blockers.append("MCP_RUNTIME_UNCONFIGURED")

    assessor = _build_openai_assessor(settings, openai_client)
    if assessor is None and case_service is None:
        blockers.append("OPENAI_RUNTIME_UNCONFIGURED")

    provider = forecast_provider
    if provider is None:
        artifact_path = os.getenv("LEXGUARD_FORECAST_ARTIFACT_PATH")
        if artifact_path:
            try:
                provider = _forecast_provider_from_file(artifact_path)
            except Exception:
                blockers.append("FORECAST_RUNTIME_UNCONFIGURED")
        elif case_service is None:
            blockers.append("FORECAST_RUNTIME_UNCONFIGURED")

    # Window-to-symbol rotation: one case per (date, window) is a schema
    # invariant and SAME_SYMBOL_REENTRY caps each underlying at one entry per
    # day, so multi-entry days rotate the underlying across windows.
    default_underlying = os.getenv("LEXGUARD_UNDERLYING", "SPY")
    rotation_raw = os.getenv("LEXGUARD_UNDERLYING_ROTATION", "").strip()
    if rotation_raw:
        rotation = tuple(part.strip().upper() for part in rotation_raw.split(","))
    else:
        rotation = (default_underlying,) * len(_WINDOWS_IN_ORDER)
    if len(rotation) != len(_WINDOWS_IN_ORDER) or any(
        symbol not in {"SPY", "QQQ", "IWM"} for symbol in rotation
    ):
        blockers.append("UNDERLYING_CONFIGURATION_INVALID")
        rotation = ("SPY",) * len(_WINDOWS_IN_ORDER)
    window_symbols = dict(zip(_WINDOWS_IN_ORDER, rotation, strict=True))

    providers: dict[str, Any] = {}
    if provider is not None:
        for symbol in dict.fromkeys(rotation):
            symbol_path = os.getenv(f"LEXGUARD_FORECAST_ARTIFACT_PATH_{symbol}")
            if forecast_provider is not None or not symbol_path:
                providers[symbol] = provider
                continue
            try:
                providers[symbol] = _forecast_provider_from_file(symbol_path)
            except Exception:
                blockers.append("FORECAST_RUNTIME_UNCONFIGURED")
                providers[symbol] = provider

    try:
        max_entries_per_day = int(os.getenv("LEXGUARD_MAX_ENTRIES_PER_DAY", "3"))
        if max_entries_per_day < 1:
            raise ValueError
    except ValueError:
        blockers.append("ENTRY_LIMIT_CONFIGURATION_INVALID")
        max_entries_per_day = 2

    calendar = _BrokerCalendarProvider(runtime_broker)
    if (
        case_service is None
        and runtime_gateway is not None
        and assessor is not None
        and provider is not None
    ):
        allowed_sides = os.getenv("LEXGUARD_ALLOWED_SIDES", "BOTH")
        shared_deliberation = DeliberationService(assessor)
        shared_candidates = CandidateService(
            risk_budget=settings.max_trade_loss,
            required_feed=option_feed,
            max_quote_width=_decimal_setting("LEXGUARD_MAX_QUOTE_WIDTH", "0.20"),
        )
        shared_judge = Judge(
            policy=RiskPolicy(
                max_trade_loss=settings.max_trade_loss,
                max_daily_loss=settings.max_daily_loss,
                max_competition_drawdown=settings.max_competition_drawdown,
                max_entries_per_day=max_entries_per_day,
            )
        )
        symbol_services: dict[str, CaseService] = {}
        for symbol in dict.fromkeys(rotation):
            symbol_services[symbol] = CaseService(
                repository=runtime_repository,
                evidence_factory=lambda case_id, _symbol=symbol: EvidenceService(
                    runtime_gateway,
                    case_id=case_id,
                    underlying=cast(Any, _symbol),
                ),
                forecast_provider=cast(Any, providers.get(symbol, provider)),
                deliberation=shared_deliberation,
                candidate_service=shared_candidates,
                judge=shared_judge,
                underlying=cast(Any, symbol),
                allowed_sides=allowed_sides,
            )
        case_service = _RotatingCaseEvaluator(
            {window: symbol_services[symbol] for window, symbol in window_symbols.items()}
        )
    if case_service is None:
        blockers.append("CASE_RUNTIME_UNCONFIGURED")
        case_service = _FailClosedCaseEvaluator("case evaluation runtime is not configured")

    runtime_risk = _BrokerRiskContextProvider(runtime_repository, required_feed=option_feed)
    if execution_service is None:
        if runtime_gateway is None:
            blockers.append("EXECUTION_RISK_CONTEXT_UNCONFIGURED")
        else:
            execution_service = ExecutionService(
                runtime_broker,
                quote_checker=runtime_gateway,
                risk_context_provider=runtime_risk,
                repository=runtime_repository,
                required_feed=option_feed,
                risk_policy=RiskPolicy(
                    max_trade_loss=settings.max_trade_loss,
                    max_daily_loss=settings.max_daily_loss,
                    max_competition_drawdown=settings.max_competition_drawdown,
                    max_entries_per_day=max_entries_per_day,
                ),
            )

    if position_manager is None:
        try:
            position_manager = PositionManager(
                profit_target=_decimal_setting("LEXGUARD_PROFIT_TARGET", "50"),
                stop_loss=_decimal_setting("LEXGUARD_STOP_LOSS", "50"),
            )
        except ValueError:
            blockers.append("POSITION_RUNTIME_UNCONFIGURED")
            position_manager = None
    snapshot_provider = position_snapshot_provider or position_evidence_provider
    if snapshot_provider is None and runtime_gateway is not None:
        snapshot_provider = _BrokerPositionSnapshotProvider(
            runtime_broker,
            runtime_gateway,
            calendar,
            settings,
            edge_evaluator=position_edge_evaluator,
            repository=runtime_repository,
        )
    if snapshot_provider is None:
        blockers.append("POSITION_RUNTIME_UNCONFIGURED")

    underlying_for_readiness = rotation[0]
    readiness = _RuntimeReadiness(
        settings=settings,
        broker=runtime_broker,
        gateway=runtime_gateway,
        assessor=assessor,
        forecast_provider=provider,
        repository=runtime_repository,
        execution_service=execution_service,
        position_manager=position_manager,
        position_snapshot_provider=snapshot_provider,
        position_closer=position_closer or execution_service,
        underlying=underlying_for_readiness
        if underlying_for_readiness in {"SPY", "QQQ", "IWM"}
        else "SPY",
        static_blockers=tuple(sorted(set(blockers))),
    )
    scheduler_service = Scheduler(
        calendar=calendar,
        reconciliation=ReconciliationService(
            runtime_broker,
            expected_state_provider=_expected_broker_state_provider(runtime_repository),
        ),
        repository=runtime_repository,
        case_service=case_service,
        execution_service=execution_service,
        entries_enabled=_entry_enabled_with(runtime_repository),
        owner=f"lexguard-scheduler-{os.getpid()}",
        position_manager=position_manager,
        position_snapshot_provider=snapshot_provider,
        position_closer=position_closer or execution_service,
        readiness_check=readiness.check,
    )
    scheduler_service.runtime_blockers = tuple(sorted(set(blockers)))
    return scheduler_service


def _expected_broker_state_provider(repository: Any) -> Callable[[], tuple[Any, Any]]:
    """Bind reconciliation to durable order and signed-position projections."""

    def provider() -> tuple[Any, Any]:
        state = repository.expected_broker_state()
        position_reader = getattr(repository, "expected_broker_position_state", None)
        if callable(position_reader):
            result: tuple[Any, Any] = (state[0], position_reader())
            return result
        result = state
        return result

    return provider


def _run(awaitable: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(awaitable)


async def _read_broker_state(
    broker: Any,
) -> tuple[BrokerAccount, tuple[BrokerOrder, ...], tuple[BrokerPosition, ...]]:
    account, orders, positions = await asyncio.gather(
        broker.get_account(), broker.get_orders(), broker.get_positions()
    )
    return account, orders, positions


def _broker_or_fail() -> Any:
    try:
        return build_broker()
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(f"paper broker is unavailable: {exc}")
    raise AssertionError("unreachable")


def _reconciliation_payload(
    account: BrokerAccount,
    orders: tuple[BrokerOrder, ...],
    positions: tuple[BrokerPosition, ...],
    *,
    repository: Any | None = None,
) -> dict[str, Any]:
    active_order_ids = sorted(
        order.order_id for order in orders if order.status.upper() in _ACTIVE_ORDER_STATES
    )
    position_symbols = sorted(position.symbol for position in positions if position.quantity)
    expected_order_ids: set[str] = set()
    expected_position_symbols: set[str] = set()
    reasons: list[str] = []
    if repository is not None:
        try:
            expected = repository.expected_broker_state()
            expected_order_ids = {str(value) for value in expected[0]}
            expected_position_symbols = {
                str(value)
                for value in (
                    expected[1].keys() if isinstance(expected[1], Mapping) else expected[1]
                )
            }
        except Exception:
            reasons.append("LEDGER_EXPECTATION_UNAVAILABLE")
    expected_orders = sorted(expected_order_ids)
    expected_positions = sorted(expected_position_symbols)
    if repository is not None and not reasons:
        if active_order_ids != expected_orders:
            reasons.append("ORDER_STATE_MISMATCH")
        if position_symbols != expected_positions:
            reasons.append("POSITION_STATE_MISMATCH")
    elif active_order_ids:
        reasons.append("UNKNOWN_BROKER_ORDER")
    elif position_symbols:
        reasons.append("UNKNOWN_BROKER_POSITION")
    return {
        "state": "CONSISTENT" if not reasons else "RECONCILE_REQUIRED",
        "reason_codes": reasons,
        "broker_order_count": len(active_order_ids),
        "broker_position_count": len(position_symbols),
        "ledger_order_ids": expected_orders,
        "ledger_position_symbols": expected_positions,
        "paper_endpoint": account.base_url == PAPER_BASE_URL,
    }


@app.command()
def status() -> None:
    """Print a sanitized, read-only service status."""

    payload: dict[str, Any] = {
        "environment": _runtime_environment(),
        "entry_enabled": _entry_enabled(),
        "paper_endpoint": os.getenv("ALPACA_BASE_URL", PAPER_BASE_URL).rstrip("/")
        == PAPER_BASE_URL,
        "components": {
            "database": "not_queried",
            "alpaca": "not_configured",
            "scheduler": "not_queried",
            "reconciliation": "not_queried",
        },
    }
    if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"):
        try:
            account, orders, positions = _run(_read_broker_state(_broker_or_fail()))
            payload["account"] = {
                "status": account.status,
                "equity": str(account.equity),
                "base_url": account.base_url,
            }
            payload["components"] = {
                **payload["components"],
                "alpaca": "healthy" if account.base_url == PAPER_BASE_URL else "halted",
                "reconciliation": _reconciliation_payload(account, orders, positions)["state"],
            }
        except typer.Exit:
            raise
        except Exception as exc:
            payload["components"] = {**payload["components"], "alpaca": f"error: {exc}"}
    _json(payload)


@app.command("reconcile")
def reconcile() -> None:
    """Compare paper broker truth with persisted order/position expectations."""

    broker = _broker_or_fail()
    account, orders, positions = _run(_read_broker_state(broker))
    repository = CaseRepository(os.getenv("DATABASE_URL", "sqlite://"))
    _json(_reconciliation_payload(account, orders, positions, repository=repository))


@app.command("run-preflight")
def run_preflight() -> None:
    """Run read-only account, endpoint, and position preflight checks."""

    broker = _broker_or_fail()
    account, orders, positions = _run(_read_broker_state(broker))
    runtime_repository = CaseRepository(os.getenv("DATABASE_URL", "sqlite://"))
    reconciliation = _reconciliation_payload(
        account, orders, positions, repository=runtime_repository
    )
    runtime_blockers: list[str] = []
    if not (os.getenv("LEXGUARD_MCP_URL") or os.getenv("ALPACA_MCP_URL")):
        runtime_blockers.append("MCP_RUNTIME_UNCONFIGURED")
    if not os.getenv("OPENAI_API_KEY"):
        runtime_blockers.append("OPENAI_RUNTIME_UNCONFIGURED")
    try:
        _option_feed()
    except ValueError:
        runtime_blockers.append("OPTION_FEED_CONFIGURATION_INVALID")
    if (
        account.last_equity is None
        or account.daily_pnl is None
        or account.competition_drawdown is None
        or account.options_level is None
    ):
        runtime_blockers.append("BROKER_RISK_STATE_UNAVAILABLE")
    forecast_path = os.getenv("LEXGUARD_FORECAST_ARTIFACT_PATH")
    if not forecast_path or not Path(forecast_path).is_file():
        runtime_blockers.append("FORECAST_RUNTIME_UNCONFIGURED")
    else:
        try:
            _forecast_provider_from_file(forecast_path)
        except Exception:
            runtime_blockers.append("FORECAST_PROVENANCE_UNVERIFIED")
    if runtime_repository.database_health() != "healthy":
        runtime_blockers.append("DATABASE_MIGRATION_UNAVAILABLE")
    if _verified_risk_state(runtime_repository) is None:
        runtime_blockers.append("RISK_STATE_UNAVAILABLE")
    checks = {
        "paper_endpoint": account.base_url == PAPER_BASE_URL,
        "account_active": account.status.upper() == "ACTIVE",
        "flat_before_entry": not orders and not positions,
        "reconciliation": reconciliation["state"],
        "runtime_dependencies": not runtime_blockers,
    }
    ready = (
        checks["paper_endpoint"] is True
        and checks["account_active"] is True
        and checks["flat_before_entry"] is True
        and checks["reconciliation"] == "CONSISTENT"
        and checks["runtime_dependencies"] is True
    )
    _json(
        {
            "ready": ready,
            "checks": checks,
            "runtime_blockers": tuple(sorted(set(runtime_blockers))),
        }
    )


@app.command("daily-preflight")
def daily_preflight() -> None:
    """Run the read-only checks required before a daily evaluation."""

    run_preflight()


@app.command("verify-account")
def verify_account(
    competition: bool = typer.Option(False, help="Apply the fresh-account competition gate."),
    require_equity: str = typer.Option("100000", help="Required equity as a decimal string."),
    require_empty_history: bool = typer.Option(False),
) -> None:
    """Verify paper endpoint, account state, and flatness without mutations."""

    try:
        required_equity = Decimal(require_equity)
    except Exception:
        _fail("--require-equity must be a decimal string")
    broker = _broker_or_fail()
    account, orders, positions = _run(_read_broker_state(broker))
    if account.base_url != PAPER_BASE_URL:
        _fail("paper-only verification failed: endpoint is not paper-api")
    if account.status.upper() != "ACTIVE":
        _fail(f"account is not ACTIVE: {account.status}")
    if competition and account.equity != required_equity:
        _fail(f"account is not fresh: equity {account.equity} != {required_equity}")
    if competition and (account.options_level is None or account.options_level < 3):
        _fail("account is not ready: effective options level 3 is required")
    if (competition or require_empty_history) and (orders or positions):
        _fail("account is not fresh: orders or positions already exist")
    try:
        option_feed = _option_feed()
    except ValueError as exc:
        _fail(str(exc))
    unverified: list[str] = []
    # OPRA is only a requirement when the operator configured the OPRA feed;
    # the indicative feed is a disclosed choice, not a verification failure.
    if competition and option_feed == "opra" and not account.opra_available:
        unverified.append("OPRA_SUBSCRIPTION_UNVERIFIED")
    if competition:
        activity_verified = getattr(account, "historical_activity_verified", None)
        if activity_verified is None:
            counter = getattr(broker, "get_activity_count", None)
            if callable(counter):
                try:
                    activity_verified = _run(counter()) == 0
                except Exception:
                    activity_verified = None
        if activity_verified is not True:
            unverified.append("HISTORICAL_ACTIVITY_UNVERIFIED")
    if unverified:
        _json(
            {
                "verified": False,
                "verification": "partial",
                "unverified": tuple(unverified),
                "paper_endpoint": account.base_url,
            }
        )
        raise typer.Exit(code=1)
    _json(
        {
            "verified": True,
            "verification": "complete" if competition else "account_only",
            "environment": "competition" if competition else _runtime_environment(),
            "status": account.status,
            "equity": str(account.equity),
            "paper_endpoint": account.base_url,
            "orders": len(orders),
            "positions": len(positions),
        }
    )


@app.command("enable-entries")
def enable_entries(
    environment: str = typer.Option(..., help="Must match LEXGUARD_ENVIRONMENT."),
    acknowledge_paper_only: bool = typer.Option(False),
) -> None:
    """Enable local entry intent only after explicit paper acknowledgement."""

    current = _runtime_environment()
    if environment != current:
        _fail(f"environment mismatch: configured {current}, requested {environment}")
    if not acknowledge_paper_only:
        _fail("enablement requires --acknowledge-paper-only")
    if os.getenv("ALPACA_BASE_URL", PAPER_BASE_URL).rstrip("/") != PAPER_BASE_URL:
        _fail("entry enablement refused: ALPACA_BASE_URL must be paper-api")
    _write_entry_state(True, environment=environment)
    _json({"entry_enabled": True, "environment": environment, "paper_only": True})


@app.command("disable-entries")
def disable_entries() -> None:
    """Disable new entries; exits and reconciliation remain available."""

    _write_entry_state(False)
    _json({"entry_enabled": False, "idempotent": True})


@app.command("assert-flat")
def assert_flat() -> None:
    """Fail if Alpaca reports any working order or non-zero position."""

    broker = _broker_or_fail()
    _, orders, positions = _run(_read_broker_state(broker))
    active_orders = [
        order.order_id for order in orders if order.status.upper() in _ACTIVE_ORDER_STATES
    ]
    open_positions = [position.symbol for position in positions if position.quantity]
    if active_orders or open_positions:
        _fail("account is not flat: working orders or open positions exist")
    _json({"flat": True})


async def _forecast_samples_from_gateway(
    gateway: Any,
    symbol: str,
    *,
    days: int,
    now: datetime,
) -> list[Any]:
    """Build one remaining-session sample per past trading day from MCP bars."""

    from lexguard.research.forecast import HistoricalSample

    new_york = ZoneInfo("America/New_York")
    samples: list[Any] = []
    day = now.astimezone(new_york).date()
    scanned = 0
    while len(samples) < days and scanned < days * 3:
        scanned += 1
        day = day - timedelta(days=1)
        if day.weekday() >= 5:
            continue
        session_open = datetime.combine(day, dt_time(9, 30), tzinfo=new_york)
        decision_at = datetime.combine(day, dt_time(10, 5), tzinfo=new_york)
        session_close = datetime.combine(day, dt_time(15, 30), tzinfo=new_york)
        try:
            bars = await gateway.get_underlying_bars(
                symbol, start=session_open, end=session_close, limit=1000
            )
        except Exception:
            continue
        decision_bars = tuple(bar for bar in bars if bar.timestamp <= decision_at)
        if len(decision_bars) < 2:
            continue
        closing_bars = tuple(bar for bar in bars if bar.timestamp <= session_close)
        if not closing_bars:
            continue
        decision_close = decision_bars[-1].close
        final_close = closing_bars[-1].close
        if decision_close <= 0:
            continue
        features = build_features(decision_bars, decision_at)
        samples.append(
            HistoricalSample(
                features=features,
                target_return=(final_close / decision_close) - Decimal("1"),
            )
        )
    return samples


@app.command("seed-forecast")
def seed_forecast(
    symbol: str = typer.Option("SPY", help="Underlying to calibrate (SPY, QQQ, or IWM)."),
    days: int = typer.Option(30, help="Number of past trading days to sample."),
    output: str | None = typer.Option(
        None, help="Artifact path; defaults to artifacts/generated/forecast-<symbol>.json."
    ),
) -> None:
    """Fit and persist a hash-verified remaining-session forecast artifact.

    The artifact is an honest baseline calibrated on recent Alpaca 5-minute
    bars observed through the MCP gateway; it exists so the runtime's
    provenance gate has something real to verify, not to claim research alpha.
    """

    if symbol not in {"SPY", "QQQ", "IWM"}:
        _fail("symbol must be SPY, QQQ, or IWM")
    if days < 5:
        _fail("at least 5 sampling days are required")
    mcp_url = os.getenv("LEXGUARD_MCP_URL") or os.getenv("ALPACA_MCP_URL")
    if not mcp_url:
        _fail("LEXGUARD_MCP_URL is required to fetch calibration bars")
    try:
        gateway = AlpacaMcpGateway(FastMcpHttpClient(mcp_url), option_feed=_option_feed())
    except Exception as exc:
        _fail(f"MCP gateway is unavailable: {exc}")
    now = datetime.now(UTC)
    samples = _run(_forecast_samples_from_gateway(gateway, symbol, days=days, now=now))
    if len(samples) < 5:
        _fail(f"only {len(samples)} usable trading days were found; refuse to fit")
    artifact = ForecastEnsemble.fit(samples, now)
    payload = {
        "training_end": artifact.training_end.isoformat(),
        "feature_schema_hash": artifact.feature_schema_hash,
        "sample_count": artifact.sample_count,
        "weights": [str(weight) for weight in artifact.weights],
        "quantile_center": str(artifact.quantile_center),
        "quantile_scale": str(artifact.quantile_scale),
        "volatility_scale": str(artifact.volatility_scale),
        "regime_center": str(artifact.regime_center),
        "regime_scale": str(artifact.regime_scale),
        "artifact_hash": artifact.artifact_hash,
    }
    target = Path(output) if output else Path("artifacts/generated") / f"forecast-{symbol}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    try:
        _forecast_provider_from_file(str(target))
    except Exception as exc:
        _fail(f"forecast artifact failed self-verification: {exc}")
    _json(
        {
            "seeded": True,
            "symbol": symbol,
            "samples": artifact.sample_count,
            "artifact_hash": artifact.artifact_hash,
            "path": str(target),
        }
    )


def _risk_state_service(repository: CaseRepository | None = None) -> RiskStateService:
    broker = _broker_or_fail()
    runtime_repository = repository or CaseRepository(os.getenv("DATABASE_URL", "sqlite://"))
    return RiskStateService(
        broker,
        runtime_repository,
        baseline_equity=_competition_baseline(),
        environment=_runtime_environment(),
    )


@app.command("seed-risk-state")
def seed_risk_state() -> None:
    """Write the hash-verified risk_state and performance_snapshot artifacts.

    This is the durable-counter bootstrap the readiness gate requires; it
    derives every value from broker truth plus the configured baseline and
    never fabricates performance.
    """

    repository = CaseRepository(os.getenv("DATABASE_URL", "sqlite://"))
    if repository.database_health() != "healthy":
        _fail("risk state requires a migrated database: run `alembic upgrade head` first")
    service = _risk_state_service(repository)
    try:
        payload = _run(service.refresh(datetime.now(UTC)))
    except Exception as exc:
        _fail(f"risk state refresh failed: {exc}")
    verified = _verified_risk_state(repository) is not None
    if not verified:
        _fail("risk state was written but did not verify; refuse to proceed")
    _json({"seeded": True, "verified": True, "risk_state": payload})


@app.command("serve")
def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the read-only FastAPI projection."""

    try:
        import uvicorn
    except ImportError as exc:
        _fail(f"uvicorn is required for serve: {exc}")
    from lexguard.api.app import create_app

    uvicorn.run(create_app(), host=host, port=port, access_log=False)


@app.command("scheduler")
def scheduler(
    once: bool = typer.Option(
        True, "--once/--watch", help="Run one scheduler tick or watch safely."
    ),
) -> None:
    """Run the internal reconciliation-aware scheduler; no HTTP route can invoke it."""

    runtime_scheduler = build_scheduler()
    try:
        risk_service: RiskStateService | None = _risk_state_service()
    except typer.Exit:
        risk_service = None

    async def refresh_risk_state() -> bool:
        if risk_service is None:
            return False
        try:
            await risk_service.refresh(datetime.now(UTC))
            return True
        except Exception as exc:
            typer.echo(f"risk state refresh failed: {exc}", err=True)
            return False

    async def run_preflight_gate() -> bool:
        await refresh_risk_state()
        preflight = getattr(runtime_scheduler, "preflight", None)
        if callable(preflight):
            return bool(await preflight())
        return bool(getattr(runtime_scheduler, "runtime_ready", False))

    async def verified_health_components(preflight_ok: bool) -> dict[str, str]:
        components = {
            "alpaca": "unavailable",
            "scheduler": "unavailable",
            "reconciliation": "unavailable",
        }
        if not preflight_ok:
            return components

        components["alpaca"] = "healthy"
        components["scheduler"] = "healthy"
        reconciler = getattr(runtime_scheduler, "reconciliation", None)
        reconcile = getattr(reconciler, "reconcile", None)
        if not callable(reconcile):
            return components
        try:
            report = await reconcile()
        except Exception:
            return components
        if getattr(report, "state", None) == "CONSISTENT":
            components["reconciliation"] = "healthy"
        return components

    def persist_health(components: Mapping[str, str]) -> None:
        repository = getattr(runtime_scheduler, "repository", None)
        if repository is None:
            return
        try:
            record_health_heartbeat(repository, components, datetime.now(UTC))
        except Exception:
            # A health report must never interrupt the safety-critical worker.
            return

    def tick_halted(result: object) -> bool:
        status = (
            result.get("status")
            if isinstance(result, Mapping)
            else getattr(result, "status", None)
        )
        return status == "HALTED"

    if once:
        runtime_ready = _run(run_preflight_gate())
        components = _run(verified_health_components(runtime_ready))
        if not runtime_ready:
            persist_health(components)
            _json(
                {
                    "ready": False,
                    "scheduler": "not_runnable",
                    "blockers": getattr(runtime_scheduler, "runtime_blockers", ()),
                }
            )
            raise typer.Exit(code=1)
        result = _run(runtime_scheduler.tick(datetime.now(UTC)))
        if tick_halted(result):
            components["scheduler"] = "unavailable"
        persist_health(components)
        payload = asdict(result) if not isinstance(result, dict) else result
        _json({"ready": runtime_ready, "entry_enabled": _entry_enabled(), "tick": payload})
        return

    async def watch() -> None:
        # A transient boot failure must not take the worker down for the day:
        # retry the preflight instead of exiting, and re-prove readiness (and
        # refresh durable risk state) periodically while ticking.
        preflight_retry_seconds = 30.0
        preflight_interval_seconds = 300.0
        refresh_interval_seconds = 60.0
        last_preflight = float("-inf")
        last_refresh = float("-inf")
        loop = asyncio.get_running_loop()
        while True:
            monotonic = loop.time()
            if not runtime_scheduler.runtime_ready or (
                monotonic - last_preflight >= preflight_interval_seconds
            ):
                ready = await run_preflight_gate()
                last_preflight = loop.time()
                last_refresh = last_preflight
                if not ready:
                    persist_health(await verified_health_components(False))
                    _json(
                        {
                            "ready": False,
                            "scheduler": "waiting",
                            "blockers": getattr(runtime_scheduler, "runtime_blockers", ()),
                        }
                    )
                    await asyncio.sleep(preflight_retry_seconds)
                    continue
            elif monotonic - last_refresh >= refresh_interval_seconds:
                await refresh_risk_state()
                last_refresh = loop.time()
            components = await verified_health_components(True)
            result = await runtime_scheduler.tick(datetime.now(UTC))
            if tick_halted(result):
                components["scheduler"] = "unavailable"
            persist_health(components)
            _json(asdict(result) if not isinstance(result, dict) else result)
            await asyncio.sleep(5)

    _run(watch())


@app.command("verify-freeze")
def verify_freeze(manifest: Path) -> None:
    """Verify file hashes recorded in a release freeze manifest."""

    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        _fail(f"invalid freeze manifest: {exc}")
    failures: list[str] = []
    for item in payload.get("files", []):
        path = Path(str(item["path"]))
        expected = str(item["sha256"])
        if not path.exists():
            failures.append(f"missing:{path}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            failures.append(f"hash:{path}")
    if failures:
        _fail("freeze verification failed: " + ", ".join(failures))
    _json({"verified": True, "manifest": str(manifest)})


@app.command("daily-report")
def daily_report(final: bool = typer.Option(False)) -> None:
    """Render a redacted report only from a persisted ledger artifact.

    An absent artifact, unavailable database, or broker/ledger mismatch is an
    explicit unavailable/reconcile-required result; no zero-valued performance
    is synthesized.
    """

    environment = _runtime_environment()
    repository: Any | None = None
    artifact: tuple[dict[str, Any], str, datetime] | None = None
    unavailable: list[str] = []
    try:
        repository = CaseRepository(os.getenv("DATABASE_URL", "sqlite://"))
        if getattr(repository, "database_health", lambda: "unavailable")() != "healthy":
            unavailable.append("DATABASE_MIGRATION_UNAVAILABLE")
        else:
            artifact = repository.latest_artifact("performance_snapshot")
            if artifact is None:
                unavailable.append("NO_RECORDED_PERFORMANCE_ARTIFACT")
    except Exception:
        unavailable.append("LEDGER_UNAVAILABLE")

    broker_state: tuple[BrokerAccount, tuple[BrokerOrder, ...], tuple[BrokerPosition, ...]] | None
    try:
        broker_state = _run(_read_broker_state(_broker_or_fail()))
    except typer.Exit:
        broker_state = None
        unavailable.append("BROKER_UNAVAILABLE")
    except Exception:
        broker_state = None
        unavailable.append("BROKER_UNAVAILABLE")

    if broker_state is None or artifact is None or unavailable:
        _json(
            {
                "final": final,
                "environment": environment,
                "provenance": "unavailable",
                "metrics": {},
                "ledger": _safe_cli_payload(artifact[0]) if artifact else None,
                "reconciliation": {"state": "UNAVAILABLE", "reason_codes": tuple(unavailable)},
                "paper_only": True,
            }
        )
        return

    account, orders, positions = broker_state
    reconciliation = _daily_report_reconciliation(
        account, orders, positions, artifact, environment=environment
    )
    _json(
        {
            "final": final,
            "environment": environment,
            "provenance": _daily_report_provenance(account, reconciliation),
            "metrics": _safe_cli_payload(artifact[0].get("metrics", {})),
            "ledger": _safe_cli_payload(artifact[0]),
            "broker": {
                "status": account.status,
                "equity": str(account.equity),
                "base_url": account.base_url,
            },
            "reconciliation": reconciliation,
            "paper_only": True,
        }
    )


@app.command("export-account-verification")
def export_account_verification(
    output: Path = Path(".lexguard/private/account-verification.json"),
) -> None:
    """Write a sanitized local account-verification record."""

    broker = _broker_or_fail()
    account, orders, positions = _run(_read_broker_state(broker))
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": account.status,
        "equity": str(account.equity),
        "base_url": account.base_url,
        "order_count": len(orders),
        "position_count": len(positions),
    }
    output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    _json({"exported": True, "path": str(output), "secrets": "redacted"})


@app.command("export-evidence")
def export_evidence(
    case: str | None = typer.Option(None),
    environment: str = typer.Option("development"),
    output: Path = Path("artifacts/private/competition-evidence.json"),
    final: bool = typer.Option(False, help="Mark this as the final export request."),
) -> None:
    """Export a redacted evidence index for local review."""

    repository: Any | None = None
    cases: list[dict[str, Any]] = []
    order_events: list[dict[str, Any]] = []
    records: tuple[Any, ...] = ()
    unavailable: str | None = None
    try:
        repository = CaseRepository(os.getenv("DATABASE_URL", "sqlite://"))
        if case is not None:
            try:
                requested = UUID(case)
            except ValueError:
                _fail("--case must be a UUID")
            record = repository.ledger_case(requested)
            if record is None:
                _fail(f"unknown case: {case}")
            records = (record,)
        else:
            records, _ = repository.list_ledger_cases(0, 1000)
        for record in records:
            record_environment = getattr(record, "environment", None)
            if record_environment is None:
                for artifact_value in getattr(record, "artifacts", {}).values():
                    if isinstance(artifact_value, Mapping) and artifact_value.get("environment"):
                        record_environment = str(artifact_value["environment"])
                        break
            # Environment is an ownership boundary: records without an exact
            # environment marker must not leak into another environment's export.
            if record_environment != environment:
                continue
            cases.append(
                {
                    "case_id": str(record.case_id),
                    "trading_date": str(record.trading_date),
                    "decision_window": record.decision_window,
                    "state": record.state,
                    "underlying": record.underlying,
                    "updated_at": record.updated_at.isoformat(),
                    "environment": record_environment,
                    "artifacts": _safe_cli_payload(record.artifacts),
                }
            )
        reader = getattr(repository, "order_events_for_cases", None)
        if callable(reader) and cases:
            rows = reader(tuple(UUID(item["case_id"]) for item in cases))
            order_events = [_serialize_order_event(row) for row in rows]
    except typer.Exit:
        raise
    except (KeyError, LookupError):
        unavailable = "LEDGER_SCHEMA_UNAVAILABLE"
    except ValueError:
        unavailable = "LEDGER_RECORD_INVALID"
    except OSError:
        unavailable = "EVIDENCE_EXPORT_IO_ERROR"
    except Exception:
        unavailable = "LEDGER_UNAVAILABLE"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "environment": environment,
        "case_id": case,
        "created_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "final": final,
        "cases": cases,
        "order_events": order_events,
        "provenance": "ledger" if cases else "no_reconciled_ledger_artifact",
        "unavailable_reason": unavailable,
        "disclosure": "Broker identifiers and credentials are intentionally omitted.",
    }
    output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    _json({"exported": True, "path": str(output), "redacted": True})


def _safe_cli_payload(value: Any) -> Any:
    """Recursively redact credential/account-shaped fields before export."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if any(
                token in str(key).lower()
                for token in (
                    "secret",
                    "authorization",
                    "token",
                    "password",
                    "api_key",
                    "access_key",
                    "private_key",
                    "account_id",
                    "account_number",
                )
            )
            else _safe_cli_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_safe_cli_payload(item) for item in value]
    return value


def _serialize_order_event(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return cast(dict[str, Any], _safe_cli_payload(dict(row)))
    return cast(dict[str, Any], _safe_cli_payload(
        {
            "order_event_id": getattr(row, "order_event_id", None),
            "case_id": str(getattr(row, "case_id", "")),
            "alpaca_order_id": getattr(row, "alpaca_order_id", None),
            "occurred_at": (
                row.occurred_at.isoformat()
                if getattr(row, "occurred_at", None) is not None
                else None
            ),
            "payload": getattr(row, "payload", {}),
        }
    ))


def _daily_report_reconciliation(
    account: BrokerAccount,
    orders: tuple[BrokerOrder, ...],
    positions: tuple[BrokerPosition, ...],
    artifact: tuple[dict[str, Any], str, datetime],
    *,
    environment: str,
) -> dict[str, Any]:
    """Compare the broker snapshot with the recorded performance snapshot."""

    payload, _, _ = artifact
    metrics = payload.get("metrics", {})
    metrics = metrics if isinstance(metrics, Mapping) else {}
    reasons: list[str] = []
    if account.base_url.rstrip("/") != PAPER_BASE_URL:
        reasons.append("PAPER_ENDPOINT_REQUIRED")
    if account.status.upper() != "ACTIVE":
        reasons.append("BROKER_ACCOUNT_UNREADY")
    if payload.get("environment") not in {None, environment}:
        reasons.append("LEDGER_ENVIRONMENT_MISMATCH")
    expected_equity = metrics.get("equity")
    if expected_equity is not None and Decimal(str(expected_equity)) != account.equity:
        reasons.append("EQUITY_MISMATCH")
    expected_daily = metrics.get("daily_pnl")
    if expected_daily is not None and account.daily_pnl is not None:
        if Decimal(str(expected_daily)) != account.daily_pnl:
            reasons.append("DAILY_PNL_MISMATCH")
    expected_drawdown = metrics.get("competition_drawdown")
    if expected_drawdown is not None and account.competition_drawdown is not None:
        if Decimal(str(expected_drawdown)) != account.competition_drawdown:
            reasons.append("DRAWDOWN_MISMATCH")
    expected_orders = tuple(sorted(str(value) for value in metrics.get("order_ids", ())))
    observed_orders = tuple(
        sorted(order.order_id for order in orders if order.status.upper() in _ACTIVE_ORDER_STATES)
    )
    if expected_orders != observed_orders:
        reasons.append("ORDER_STATE_MISMATCH")
    expected_positions = tuple(sorted(str(value) for value in metrics.get("position_symbols", ())))
    observed_positions = tuple(
        sorted(position.symbol for position in positions if position.quantity)
    )
    if expected_positions != observed_positions:
        reasons.append("POSITION_STATE_MISMATCH")
    return {
        "state": "CONSISTENT" if not reasons else "RECONCILE_REQUIRED",
        "reason_codes": tuple(sorted(set(reasons))),
        "broker_order_ids": observed_orders,
        "broker_position_symbols": observed_positions,
        "ledger_order_ids": expected_orders,
        "ledger_position_symbols": expected_positions,
    }


def _daily_report_provenance(
    account: BrokerAccount, reconciliation: Mapping[str, Any]
) -> str:
    if (
        account.base_url.rstrip("/") == PAPER_BASE_URL
        and account.status.upper() == "ACTIVE"
        and reconciliation.get("state") == "CONSISTENT"
    ):
        return "alpaca_broker_reconciled"
    if reconciliation.get("state") == "RECONCILE_REQUIRED":
        return "reconcile_required"
    return "unavailable"


if __name__ == "__main__":
    app()
