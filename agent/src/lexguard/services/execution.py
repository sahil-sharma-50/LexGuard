"""Bounded, single-entry paper order lifecycle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from lexguard.adapters.alpaca_trading import (
    BROKER_ACTIVE_ORDER_STATES,
    BROKER_CANCELED_ORDER_STATES,
    BROKER_FILLED_ORDER_STATES,
    BROKER_KNOWN_ORDER_STATES,
    BROKER_REJECTED_ORDER_STATES,
    PAPER_BASE_URL,
    BrokerAccount,
    BrokerAmbiguousOrderError,
    BrokerClock,
    BrokerMutationError,
    BrokerOrder,
    BrokerPosition,
    position_is_long,
)
from lexguard.adapters.repository import entry_client_order_id, entry_intent_key
from lexguard.domain.hashing import canonical_sha256
from lexguard.domain.models import (
    AllowedUnderlying,
    ExecutionRecord,
    OptionQuote,
    TradeCertificate,
)
from lexguard.domain.policy import RiskContext, RiskPolicy

REPLACE_AFTER = timedelta(seconds=0)
CANCEL_AFTER = timedelta(seconds=90)
MAX_QUOTE_AGE = timedelta(seconds=30)
ExecutionState = Literal[
    "SUBMITTED",
    "REPLACED",
    "FILLED",
    "CANCELED",
    "REJECTED",
    "RECONCILE_REQUIRED",
]
CloseState = Literal[
    "CLOSED", "MANAGING", "SUBMITTED", "REJECTED", "RECONCILE_REQUIRED", "PENDING_OWNER"
]
_KNOWN_ORDER_STATES = BROKER_KNOWN_ORDER_STATES


@dataclass(frozen=True, slots=True)
class _ObservedExecutionState:
    """The broker orders and positions observed at one lifecycle boundary."""

    orders: tuple[BrokerOrder, ...]
    positions: tuple[BrokerPosition, ...]


class ExecutionBroker(Protocol):
    base_url: str

    async def get_account(self) -> BrokerAccount: ...

    async def get_positions(self) -> tuple[BrokerPosition, ...]: ...

    async def get_orders(self) -> tuple[BrokerOrder, ...]: ...

    async def get_clock(self) -> BrokerClock: ...

    async def submit_mleg(
        self,
        certificate: TradeCertificate,
        limit_price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> BrokerOrder: ...

    async def get_order(self, order_id: str) -> BrokerOrder: ...

    async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder: ...

    async def replace_order(self, order_id: str, limit_price: Decimal) -> BrokerOrder: ...

    async def cancel_order(self, order_id: str) -> None: ...


class CloseBroker(Protocol):
    async def submit_close_mleg(
        self,
        positions: Sequence[BrokerPosition],
        *,
        limit_price: Decimal,
        client_order_id: str | None = None,
    ) -> BrokerOrder: ...


class QuoteChecker(Protocol):
    async def get_option_chain(
        self,
        underlying_symbol: AllowedUnderlying,
        *,
        expiration_date: date | str | None = None,
        limit: int = 100,
    ) -> tuple[OptionQuote, ...]: ...


class ExecutionRiskContextProvider(Protocol):
    """Build a current policy context from broker observations and durable ledger facts."""

    async def build(
        self,
        certificate: TradeCertificate,
        now: datetime,
        account: BrokerAccount,
        positions: tuple[BrokerPosition, ...],
        orders: tuple[BrokerOrder, ...],
        clock: BrokerClock,
        quotes: tuple[OptionQuote, ...],
    ) -> RiskContext: ...


class CloseResult:
    """Result of submitting one atomic inverse-position close intent."""

    def __init__(
        self,
        order_id: str,
        reason: str,
        symbols: tuple[str, ...],
        *,
        state: CloseState = "RECONCILE_REQUIRED",
        flat: bool = False,
        case_id: UUID | None = None,
        order_observation: BrokerOrder | None = None,
        signed_quantities: dict[str, int] | None = None,
        client_order_id: str | None = None,
    ) -> None:
        self.order_id = order_id
        self.reason = reason
        self.symbols = symbols
        self.state = state
        self.flat = flat
        self.case_id = case_id
        self.order_observation = order_observation
        self.signed_quantities = dict(signed_quantities or {})
        self.client_order_id = client_order_id
        self.intent_key: str | None = None


def _close_intent_key(positions: Sequence[BrokerPosition]) -> str:
    canonical = sorted(
        (
            {
                "symbol": position.symbol,
                "quantity": position.quantity,
                "side": position.side.strip().lower(),
            }
            for position in positions
        ),
        key=lambda value: (str(value["symbol"]), int(str(value["quantity"]))),
    )
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ExecutionService:
    def __init__(
        self,
        broker: ExecutionBroker,
        *,
        replace_after: timedelta = REPLACE_AFTER,
        cancel_after: timedelta = CANCEL_AFTER,
        quote_checker: QuoteChecker | None = None,
        risk_context_provider: ExecutionRiskContextProvider | None = None,
        risk_policy: RiskPolicy | None = None,
        repository: Any | None = None,
        close_intent_repository: Any | None = None,
        worker_id: str | None = None,
        required_feed: str = "opra",
    ) -> None:
        if replace_after < timedelta(0) or cancel_after <= replace_after:
            raise ValueError("execution deadlines must be ordered and non-negative")
        if required_feed not in {"opra", "indicative"}:
            raise ValueError("required_feed must be opra or indicative")
        self.broker = broker
        self.replace_after = replace_after
        self.cancel_after = cancel_after
        self.quote_checker = quote_checker
        self.risk_context_provider = risk_context_provider
        self.risk_policy = risk_policy or RiskPolicy()
        self.repository = repository
        self.close_intent_repository = close_intent_repository or repository
        self._close_worker_id = worker_id or f"execution-service:{uuid4().hex}"
        self.required_feed = required_feed

    async def execute(self, certificate: TradeCertificate, now: datetime) -> ExecutionRecord:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("execution time must be timezone-aware")
        if now >= certificate.expires_at:
            return self._record(certificate, "REJECTED", now)
        if certificate.proposal_hash != canonical_sha256(certificate.candidate):
            return self._record(certificate, "REJECTED", now)

        try:
            account, positions, orders, clock = await self._preflight()
        except Exception:
            return self._record(certificate, "RECONCILE_REQUIRED", now)
        if self.broker.base_url.rstrip("/") != PAPER_BASE_URL or account.base_url != PAPER_BASE_URL:
            return self._record(certificate, "REJECTED", now)
        if account.status.upper() != "ACTIVE" or not clock.is_open:
            return self._record(certificate, "REJECTED", now)
        if (
            account.last_equity is None
            or account.daily_pnl is None
            or account.competition_drawdown is None
            or account.options_level is None
        ):
            return self._record(certificate, "RECONCILE_REQUIRED", now)
        if not all(
            value.is_finite()
            for value in (
                account.equity,
                account.last_equity,
                account.daily_pnl,
                account.competition_drawdown,
            )
        ):
            return self._record(certificate, "RECONCILE_REQUIRED", now)
        if account.equity <= 0 or account.equity < certificate.account_equity:
            return self._record(certificate, "REJECTED", now)
        if positions or orders:
            return self._record(certificate, "RECONCILE_REQUIRED", now)
        if self.quote_checker is None or self.risk_context_provider is None:
            return self._record(certificate, "REJECTED", now)
        try:
            quotes = await self._refresh_quotes(certificate, now)
            context = await self.risk_context_provider.build(
                certificate, now, account, positions, orders, clock, quotes
            )
            context = context.model_copy(
                update={"entry_attempt": True, "certificate_expires_at": certificate.expires_at}
            )
            if not self.risk_policy.evaluate(certificate.candidate, context).allowed:
                return self._record(certificate, "REJECTED", now)
        except Exception:
            return self._record(certificate, "RECONCILE_REQUIRED", now)

        try:
            initial_limit, replacement_limit = self._entry_limits(certificate, quotes)
        except Exception:
            return self._record(certificate, "RECONCILE_REQUIRED", now)
        # The cancel ladder is anchored to submission time, not certificate
        # issuance: evaluation runs minutes before execution, so an
        # issuance-anchored deadline would cancel every order instantly.
        deadline_at = now + self.cancel_after
        intent_key = entry_intent_key(certificate.certificate_id)
        client_id = entry_client_order_id(certificate.certificate_id)
        intent_repository = self.repository
        order_ids: list[str] = []
        claim_token: str | None = None
        if intent_repository is not None:
            creator = getattr(intent_repository, "create_or_claim_entry_intent", None)
            if not callable(creator):
                return self._record(certificate, "RECONCILE_REQUIRED", now)
            claim_token = f"{self._close_worker_id}:{uuid4().hex}"
            try:
                claimed = creator(
                    intent_key,
                    certificate.case_id,
                    certificate.certificate_id,
                    deadline_at,
                    owner=self._close_worker_id,
                    client_order_id=client_id,
                    now=now,
                    claim_token=claim_token,
                )
            except TypeError:
                claimed = creator(
                    intent_key,
                    certificate.case_id,
                    certificate.certificate_id,
                    deadline_at,
                    owner=self._close_worker_id,
                    client_order_id=client_id,
                    now=now,
                )
            existing = getattr(claimed, "record", claimed)
            order_ids = list(getattr(existing, "order_ids", ()) or ())
            if not getattr(claimed, "claimed", True):
                # An unexpired lease belongs to another worker.  Even when
                # that worker persisted an order id, adopting it here could
                # race into replace/cancel (or submit with no ``submitted``
                # object).  Repository claim expiry is the only adoption
                # proof; until then the safe outcome is reconciliation.
                return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids)
        adopted = bool(order_ids)
        if not order_ids:
            try:
                try:
                    submitted = await self.broker.submit_mleg(
                        certificate,
                        limit_price=initial_limit,
                        client_order_id=client_id,
                    )
                except TypeError:
                    if intent_repository is not None:
                        return self._record(certificate, "RECONCILE_REQUIRED", now)
                    submitted = await self.broker.submit_mleg(
                        certificate, limit_price=initial_limit
                    )
            except Exception:
                return self._record(certificate, "RECONCILE_REQUIRED", now)
            order_ids = [submitted.order_id]
            if intent_repository is not None:
                try:
                    self._update_entry_intent(
                        intent_repository,
                        intent_key,
                        state="SUBMITTED",
                        order_ids=order_ids,
                        now=now,
                        claim_token=claim_token,
                    )
                except Exception:
                    return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids)
        observed = await self._observe(order_ids)
        if observed is None:
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids)
        decision = self._decide(certificate, now, observed, order_ids)
        if decision is not None:
            return decision

        if adopted:
            # An adopted chain was submitted by an earlier attempt of this
            # worker; its persisted deadline drives the cancel ladder through
            # reconcile_entry_orders, and replacing it here could race a fill.
            return self._record(certificate, "SUBMITTED", now, order_ids, observed)
        if self.replace_after > timedelta(0):
            # A deferred replacement is handled on a later tick; the freshly
            # submitted order stays working until its submission deadline.
            return self._record(certificate, "SUBMITTED", now, order_ids, observed)

        try:
            replacement = await self.broker.replace_order(order_ids[0], replacement_limit)
            if replacement.order_id not in order_ids:
                order_ids.append(replacement.order_id)
        except BrokerMutationError:
            observed_after_race = await self._observe(order_ids)
            if observed_after_race is None:
                return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids)
            race_decision = self._decide(
                certificate, now, observed_after_race, order_ids
            )
            return race_decision or self._record(
                certificate, "RECONCILE_REQUIRED", now, order_ids, observed_after_race
            )
        except Exception:
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids)

        observed_after_replace = await self._observe(order_ids)
        if observed_after_replace is None:
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids)
        replacement_decision = self._decide(
            certificate, now, observed_after_replace, order_ids
        )
        if replacement_decision is not None:
            if (
                replacement_decision.state == "RECONCILE_REQUIRED"
                and any(self._is_filled(row) for row in observed_after_replace.orders)
                and any(self._is_working(row) for row in observed_after_replace.orders)
            ):
                return await self._cancel_working_siblings(
                    certificate, now, order_ids, observed_after_replace
                )
            return replacement_decision
        return self._record(
            certificate, "REPLACED", now, order_ids, observed_after_replace
        )

    async def reconcile_entry_orders(self, now: datetime) -> tuple[ExecutionRecord, ...]:
        """Poll durable entry chains after a restart without submitting again."""

        # Some scheduler integrations expose the durable entry-chain reader
        # through the close-intent repository.  Reuse that adapter when a
        # separate repository was not supplied so restart polling remains
        # deterministic across process boundaries.
        repository = self.repository or self.close_intent_repository
        reader = getattr(repository, "active_entry_order_chains", None)
        if not callable(reader):
            return ()
        results: list[ExecutionRecord] = []
        for chain in reader():
            try:
                certificate = TradeCertificate.model_validate(chain["certificate"])
                order_ids = list(chain["order_ids"])
                if not order_ids and chain.get("client_order_id"):
                    order_ids = await self._find_client_order(str(chain["client_order_id"]))
                if not order_ids:
                    result = self._record(certificate, "RECONCILE_REQUIRED", now)
                    results.append(result)
                    continue
                observed = await self._observe(order_ids)
                if observed is None:
                    result = self._record(certificate, "RECONCILE_REQUIRED", now, order_ids)
                else:
                    decision = self._decide(certificate, now, observed, order_ids)
                    deadline = chain.get("deadline_at")
                    if isinstance(deadline, str):
                        deadline = datetime.fromisoformat(deadline)
                    expired = isinstance(deadline, datetime) and now >= deadline
                    has_working = any(self._is_working(order) for order in observed.orders)
                    has_filled = any(self._is_filled(order) for order in observed.orders)
                    if deadline is None and has_working:
                        # A legacy chain without a deadline cannot be allowed
                        # to remain working forever.  Cancel it and reconcile
                        # the resulting broker truth before accepting anything.
                        result = await self._cancel_working_siblings(
                            certificate, now, order_ids, observed
                        )
                    elif deadline is None:
                        result = self._record(
                            certificate, "RECONCILE_REQUIRED", now, order_ids, observed
                        )
                    elif has_working and (expired or has_filled):
                        result = await self._cancel_working_siblings(
                            certificate, now, order_ids, observed
                        )
                    elif decision is not None:
                        result = decision
                    elif observed.orders and all(
                        self._is_working(order) for order in observed.orders
                    ):
                        result = self._record(
                            certificate, "SUBMITTED", now, order_ids, observed
                        )
                    else:
                        result = self._record(
                            certificate, "RECONCILE_REQUIRED", now, order_ids, observed
                        )
            except Exception as exc:
                raise RuntimeError("durable entry order chain is invalid") from exc
            results.append(result)
        return tuple(results)

    async def close(
        self,
        position: BrokerPosition | Sequence[BrokerPosition],
        reason: str,
        now: datetime,
        case_id: UUID | None = None,
    ) -> CloseResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("close time must be timezone-aware")
        if not reason:
            raise ValueError("close reason must be non-empty")
        positions = (position,) if isinstance(position, BrokerPosition) else tuple(position)
        if not positions:
            raise ValueError("close requires at least one actual broker position")
        if getattr(self.broker, "base_url", "").rstrip("/") != PAPER_BASE_URL:
            raise RuntimeError("paper endpoint is required for closes")
        if self.quote_checker is None:
            raise RuntimeError("close requires current configured-feed quotes")
        close_broker = self.broker
        if not hasattr(close_broker, "submit_close_mleg"):
            raise RuntimeError("broker does not support atomic closes")
        symbols = tuple(item.symbol for item in positions)
        signed_quantities = {
            item.symbol: (-abs(item.quantity) if position_is_long(item) else abs(item.quantity))
            for item in positions
        }
        intent_key = _close_intent_key(positions)
        client_id = f"lexguard-close-{intent_key[:32]}"
        intent_repository = self.close_intent_repository
        claim_token: str | None = None
        existing: Any | None = None
        existing_case_id = case_id
        if intent_repository is not None:
            claim = getattr(intent_repository, "create_or_claim_close_intent", None)
            if callable(claim):
                claim_token = f"{self._close_worker_id}:{uuid4().hex}"
                try:
                    claimed = claim(
                        intent_key,
                        symbols,
                        reason,
                        owner=self._close_worker_id,
                        now=now,
                        case_id=case_id,
                        claim_token=claim_token,
                        signed_quantities=signed_quantities,
                        deadline_at=now + self.cancel_after,
                        client_order_id=client_id,
                    )
                except TypeError:
                    claimed = claim(
                        intent_key,
                        symbols,
                        reason,
                        owner=self._close_worker_id,
                        now=now,
                        case_id=case_id,
                    )
                if getattr(claimed, "claimed", True) is False:
                    return CloseResult(
                        "", reason, symbols, state="PENDING_OWNER"
                    )
                existing = getattr(claimed, "record", claimed)
            else:
                existing = intent_repository.get_close_intent(intent_key)
                if existing is None:
                    creator = getattr(intent_repository, "create_close_intent", None)
                    if callable(creator):
                        try:
                            existing = creator(
                                intent_key,
                                symbols,
                                reason,
                                now=now,
                                case_id=case_id,
                                signed_quantities=signed_quantities,
                                deadline_at=now + self.cancel_after,
                                client_order_id=client_id,
                            )
                        except TypeError:
                            existing = creator(intent_key, symbols, reason, now=now)
                if existing is None:
                    return CloseResult("", reason, symbols, state="RECONCILE_REQUIRED")
            existing_case_id = getattr(existing, "case_id", None) or case_id
            client_id = getattr(existing, "client_order_id", None) or client_id
            if getattr(existing, "state", None) == "CLOSED":
                return CloseResult(
                    getattr(existing, "order_id", "") or "",
                    reason,
                    symbols,
                    state="CLOSED",
                    flat=True,
                    case_id=existing_case_id,
                    client_order_id=client_id,
                )
            if getattr(existing, "order_id", None):
                result = await self._reconcile_close(
                    intent_key,
                    str(existing.order_id),
                    reason,
                    symbols,
                    now,
                    claim_token,
                    existing_case_id,
                    client_id,
                )
                result.signed_quantities = dict(
                    getattr(existing, "signed_quantities", {}) or signed_quantities
                )
                return result

        # A submit may have succeeded immediately before a process crash.  A
        # client-id lookup covers every broker status before any resubmit.
        try:
            recovered = await self._find_client_order(client_id)
        except BrokerAmbiguousOrderError:
            return CloseResult(
                "",
                reason,
                symbols,
                state="RECONCILE_REQUIRED",
                case_id=existing_case_id,
                signed_quantities=signed_quantities,
                client_order_id=client_id,
            )
        if recovered:
            recovered_order_id = recovered[0]
            if intent_repository is not None:
                try:
                    self._update_close_intent(
                        intent_repository,
                        intent_key,
                        state="MANAGING",
                        order_id=recovered_order_id,
                        now=now,
                        claim_token=claim_token,
                    )
                except Exception:
                    return CloseResult(
                        recovered_order_id,
                        reason,
                        symbols,
                        state="RECONCILE_REQUIRED",
                        case_id=existing_case_id,
                        signed_quantities=signed_quantities,
                        client_order_id=client_id,
                    )
            result = await self._reconcile_close(
                intent_key,
                recovered_order_id,
                reason,
                symbols,
                now,
                claim_token,
                existing_case_id,
                client_id,
            )
            result.signed_quantities = dict(
                getattr(existing, "signed_quantities", {}) or signed_quantities
            )
            return result

        get_orders = getattr(self.broker, "get_orders", None)
        if callable(get_orders):
            try:
                existing_orders = await get_orders()
            except Exception:
                return CloseResult(
                    "", reason, symbols, state="RECONCILE_REQUIRED", case_id=case_id,
                    client_order_id=client_id,
                )
        else:
            existing_orders = ()
        if any(self._is_working(order) for order in existing_orders):
            if intent_repository is not None:
                self._persist_close_state(
                    intent_key, "RECONCILE_REQUIRED", None, now, claim_token
                )
            return CloseResult(
                "", reason, symbols, state="RECONCILE_REQUIRED", case_id=case_id,
                client_order_id=client_id,
            )

        try:
            limit_price = await self._close_limit_price(positions, now)
        except Exception:
            if intent_repository is None:
                raise
            self._persist_close_state(intent_key, "INTENT", None, now, claim_token)
            return CloseResult(
                "",
                reason,
                symbols,
                state="RECONCILE_REQUIRED",
                case_id=case_id,
                signed_quantities=signed_quantities,
                client_order_id=client_id,
            )
        try:
            try:
                order = await close_broker.submit_close_mleg(
                    positions, limit_price=limit_price, client_order_id=client_id
                )
            except TypeError:
                if intent_repository is not None:
                    return CloseResult(
                        "",
                        reason,
                        symbols,
                        state="RECONCILE_REQUIRED",
                        case_id=case_id,
                        signed_quantities=signed_quantities,
                        client_order_id=client_id,
                    )
                order = await close_broker.submit_close_mleg(
                    positions, limit_price=limit_price
                )
        except Exception:
            return CloseResult(
                "", reason, symbols, state="RECONCILE_REQUIRED", case_id=case_id,
                signed_quantities=signed_quantities, client_order_id=client_id,
            )
        if intent_repository is not None:
            try:
                self._update_close_intent(
                    intent_repository,
                    intent_key,
                    state="MANAGING",
                    order_id=order.order_id,
                    now=now,
                    claim_token=claim_token,
                )
            except Exception:
                return CloseResult(
                    order.order_id, reason, symbols, state="RECONCILE_REQUIRED", case_id=case_id,
                    client_order_id=client_id,
                )
        try:
            observed_order = await self.broker.get_order(order.order_id)
            observed_positions = await self.broker.get_positions()
        except Exception:
            return CloseResult(
                order.order_id,
                reason,
                symbols,
                state="RECONCILE_REQUIRED",
                case_id=case_id,
                client_order_id=client_id,
            )
        if observed_order.order_id != order.order_id:
            return CloseResult(
                order.order_id, reason, symbols, state="RECONCILE_REQUIRED", case_id=case_id
            )
        if self._is_filled(observed_order):
            flat = self._target_positions_flat(symbols, observed_positions)
            result = CloseResult(
                order.order_id,
                reason,
                symbols,
                state="CLOSED" if flat else "RECONCILE_REQUIRED",
                flat=flat,
                case_id=case_id,
                order_observation=observed_order,
                signed_quantities=signed_quantities,
                client_order_id=client_id,
            )
            result.intent_key = intent_key
            if intent_repository is not None:
                self._persist_close_state(
                    intent_key,
                    "CLOSED" if flat else "RECONCILE_REQUIRED",
                    order.order_id,
                    now,
                    claim_token,
                )
            return result
        if self._is_rejected(observed_order) or self._is_canceled(observed_order):
            result = CloseResult(
                order.order_id,
                reason,
                symbols,
                state="REJECTED",
                case_id=case_id,
                order_observation=observed_order,
                signed_quantities=signed_quantities,
                client_order_id=client_id,
            )
            result.intent_key = intent_key
            if intent_repository is not None:
                self._persist_close_state(intent_key, "REJECTED", order.order_id, now, claim_token)
            return result
        if self._is_partial(observed_order):
            result = CloseResult(
                order.order_id,
                reason,
                symbols,
                state="RECONCILE_REQUIRED",
                case_id=case_id,
                order_observation=observed_order,
                signed_quantities=signed_quantities,
                client_order_id=client_id,
            )
            result.intent_key = intent_key
            if intent_repository is not None:
                self._persist_close_state(
                    intent_key, "RECONCILE_REQUIRED", order.order_id, now, claim_token
                )
            return result
        if self._is_working(observed_order):
            result = CloseResult(
                order.order_id,
                reason,
                symbols,
                state="MANAGING" if intent_repository is not None else "SUBMITTED",
                case_id=case_id,
                order_observation=observed_order,
                signed_quantities=signed_quantities,
                client_order_id=client_id,
            )
            result.intent_key = intent_key
            return result
        result = CloseResult(
            order.order_id,
            reason,
            symbols,
            state="RECONCILE_REQUIRED",
            case_id=case_id,
            order_observation=observed_order,
            signed_quantities=signed_quantities,
            client_order_id=client_id,
        )
        result.intent_key = intent_key
        return result

    async def reconcile_close_intents(self, now: datetime) -> tuple[CloseResult, ...]:
        """Observe durable close intents after a process restart."""

        repository = self.close_intent_repository or self.repository
        reader = getattr(repository, "active_close_intents", None)
        if not callable(reader):
            return ()
        results: list[CloseResult] = []
        for intent in reader():
            order_id = getattr(intent, "order_id", None)
            symbols = tuple(getattr(intent, "symbols", ()))
            reason = str(getattr(intent, "reason", "RECONCILE"))
            case_id = getattr(intent, "case_id", None)
            if not order_id:
                client_id = getattr(intent, "client_order_id", None)
                if not client_id:
                    client_id = f"lexguard-close-{str(getattr(intent, 'intent_key', ''))[:32]}"
                try:
                    recovered = await self._find_client_order(str(client_id))
                except BrokerAmbiguousOrderError:
                    recovered = []
                if len(recovered) == 1:
                    updater = getattr(repository, "update_close_intent", None)
                    if not callable(updater):
                        results.append(
                            CloseResult(
                                "",
                                reason,
                                symbols,
                                state="RECONCILE_REQUIRED",
                                case_id=case_id,
                                client_order_id=str(client_id),
                            )
                        )
                        continue
                    try:
                        updater(
                            str(getattr(intent, "intent_key", "")),
                            state="MANAGING",
                            order_id=recovered[0],
                            now=now,
                            claim_token=getattr(intent, "claim_token", None),
                        )
                    except Exception:
                        results.append(
                            CloseResult(
                                recovered[0],
                                reason,
                                symbols,
                                state="RECONCILE_REQUIRED",
                                case_id=case_id,
                                client_order_id=str(client_id),
                            )
                        )
                        continue
                    result = await self._reconcile_close(
                        str(getattr(intent, "intent_key", "")),
                        recovered[0],
                        reason,
                        symbols,
                        now,
                        getattr(intent, "claim_token", None),
                        case_id,
                        str(client_id),
                    )
                    result.signed_quantities = dict(
                        getattr(intent, "signed_quantities", {}) or {}
                    )
                    results.append(result)
                    continue
                results.append(
                    CloseResult(
                        "",
                        reason,
                        symbols,
                        state="RECONCILE_REQUIRED",
                        case_id=case_id,
                        client_order_id=str(client_id),
                    )
                )
                continue
            result = await self._reconcile_close(
                str(getattr(intent, "intent_key", "")),
                str(order_id),
                reason,
                symbols,
                now,
                getattr(intent, "claim_token", None),
                case_id,
                getattr(intent, "client_order_id", None),
            )
            result.signed_quantities = dict(getattr(intent, "signed_quantities", {}) or {})
            results.append(result)
        return tuple(results)

    async def _reconcile_close(
        self,
        intent_key: str,
        order_id: str,
        reason: str,
        symbols: tuple[str, ...],
        now: datetime,
        claim_token: str | None = None,
        case_id: UUID | None = None,
        client_order_id: str | None = None,
    ) -> CloseResult:
        try:
            observed_order = await self.broker.get_order(order_id)
            observed_positions = await self.broker.get_positions()
        except Exception:
            result = CloseResult(
                order_id,
                reason,
                symbols,
                state="RECONCILE_REQUIRED",
                case_id=case_id,
                client_order_id=client_order_id,
            )
            result.intent_key = intent_key
            return result
        if observed_order.order_id != order_id:
            result = CloseResult(
                order_id,
                reason,
                symbols,
                state="RECONCILE_REQUIRED",
                case_id=case_id,
                client_order_id=client_order_id,
            )
            result.intent_key = intent_key
            return result
        if self._is_filled(observed_order):
            flat = self._target_positions_flat(symbols, observed_positions)
            state: CloseState = "CLOSED" if flat else "RECONCILE_REQUIRED"
        elif self._is_rejected(observed_order) or self._is_canceled(observed_order):
            flat = False
            state = "REJECTED"
        elif self._is_partial(observed_order):
            flat = False
            state = "RECONCILE_REQUIRED"
        elif self._is_working(observed_order):
            flat = False
            state = "MANAGING" if self.close_intent_repository is not None else "SUBMITTED"
        else:
            flat = False
            state = "RECONCILE_REQUIRED"
        if self.close_intent_repository is not None:
            self._persist_close_state(intent_key, state, order_id, now, claim_token)
        result = CloseResult(
            order_id,
            reason,
            symbols,
            state=state,
            flat=flat,
            case_id=case_id,
            order_observation=observed_order,
            client_order_id=client_order_id,
        )
        result.intent_key = intent_key
        return result

    async def _find_client_order(self, client_order_id: str) -> list[str]:
        """Find a pre-submit order across all broker lifecycle statuses."""

        lookup = getattr(self.broker, "get_order_by_client_id", None)
        if not callable(lookup):
            return []
        try:
            result = await lookup(client_order_id)
        except BrokerAmbiguousOrderError:
            raise
        except Exception:
            return []
        if isinstance(result, tuple | list):
            found: list[str] = []
            for row in result:
                order_id = getattr(row, "order_id", None)
                returned_client_id = getattr(row, "client_order_id", None)
                if order_id and (
                    returned_client_id is None
                    or str(returned_client_id) == client_order_id
                ):
                    found.append(str(order_id))
            if len(found) > 1:
                raise BrokerAmbiguousOrderError(
                    f"multiple orders matched client id {client_order_id}"
                )
            return found
        order_id = getattr(result, "order_id", None)
        if not order_id:
            return []
        returned_client_id = getattr(result, "client_order_id", None)
        if returned_client_id is not None and str(returned_client_id) != client_order_id:
            return []
        return [str(order_id)]

    @staticmethod
    def _target_positions_flat(
        symbols: Sequence[str], positions: Sequence[BrokerPosition]
    ) -> bool:
        """Check only target legs; unrelated broker positions reconcile separately."""

        targets = set(symbols)
        return not any(position.quantity and position.symbol in targets for position in positions)

    @staticmethod
    def _update_entry_intent(
        repository: Any,
        intent_key: str,
        *,
        state: str,
        order_ids: Sequence[str],
        now: datetime,
        claim_token: str | None,
    ) -> Any:
        updater = getattr(repository, "update_entry_intent", None)
        if not callable(updater):
            raise RuntimeError("durable entry intent updater is unavailable")
        try:
            return updater(
                intent_key,
                state=state,
                order_ids=order_ids,
                now=now,
                claim_token=claim_token,
            )
        except TypeError:
            return updater(intent_key, state=state, order_ids=order_ids, now=now)

    def _persist_close_state(
        self,
        intent_key: str,
        state: str,
        order_id: str | None,
        now: datetime,
        claim_token: str | None = None,
    ) -> None:
        repository = self.close_intent_repository
        if repository is None or not intent_key:
            return
        updater = getattr(repository, "update_close_intent", None)
        if not callable(updater):
            return
        self._update_close_intent(
            repository,
            intent_key,
            state=state,
            order_id=order_id,
            now=now,
            claim_token=claim_token,
        )

    @staticmethod
    def _update_close_intent(
        repository: Any,
        intent_key: str,
        *,
        state: str,
        order_id: str | None,
        now: datetime,
        claim_token: str | None,
    ) -> Any:
        try:
            return repository.update_close_intent(
                intent_key,
                state=state,
                order_id=order_id,
                now=now,
                claim_token=claim_token,
            )
        except TypeError:
            return repository.update_close_intent(
                intent_key, state=state, order_id=order_id, now=now
            )

    async def _preflight(
        self,
    ) -> tuple[BrokerAccount, tuple[BrokerPosition, ...], tuple[BrokerOrder, ...], BrokerClock]:
        account = await self.broker.get_account()
        positions = await self.broker.get_positions()
        orders = await self.broker.get_orders()
        clock = await self.broker.get_clock()
        return account, positions, orders, clock

    async def _refresh_quotes(
        self, certificate: TradeCertificate, now: datetime
    ) -> tuple[OptionQuote, ...]:
        checker = self.quote_checker
        if checker is None:
            raise RuntimeError("current quotes are required")
        quotes = await checker.get_option_chain(
            certificate.candidate.underlying,
            expiration_date=certificate.candidate.expiration,
        )
        by_symbol = {quote.symbol: quote for quote in quotes}
        required = {leg.symbol for leg in certificate.candidate.legs}
        if required - by_symbol.keys():
            raise ValueError("one or more certified option quotes disappeared")
        selected = tuple(by_symbol[leg.symbol] for leg in certificate.candidate.legs)
        for leg, quote in zip(certificate.candidate.legs, selected, strict=True):
            if (
                quote.symbol != leg.symbol
                or quote.underlying != leg.underlying
                or quote.expiration != leg.expiration
                or quote.strike != leg.strike
                or quote.right != leg.right
            ):
                raise ValueError(
                    "refreshed option quote contract identity differs from certificate"
                )
        if any(
            quote.feed != self.required_feed
            or quote.bid is None
            or quote.ask is None
            or quote.bid > quote.ask
            for quote in selected
        ):
            raise ValueError("certified option quotes are not executable configured-feed quotes")
        if any(
            quote.observed_at.tzinfo is None
            or quote.observed_at.utcoffset() is None
            or quote.observed_at > now
            or now - quote.observed_at > MAX_QUOTE_AGE
            for quote in selected
        ):
            raise ValueError("certified option quote timestamp is invalid")
        return selected

    @staticmethod
    def _entry_limits(
        certificate: TradeCertificate, quotes: Sequence[OptionQuote]
    ) -> tuple[Decimal, Decimal]:
        """Derive an executable current limit without relaxing certificate bounds."""

        midpoint = Decimal("0")
        executable = Decimal("0")
        for leg, quote in zip(certificate.candidate.legs, quotes, strict=True):
            assert quote.bid is not None and quote.ask is not None
            mid = (quote.bid + quote.ask) / Decimal("2")
            if leg.side == "BUY":
                midpoint += mid
                executable += quote.ask
            else:
                midpoint -= mid
                executable -= quote.bid
        bound = certificate.candidate.entry_limit
        initial = min(midpoint, bound)
        replacement = min(executable, bound)
        if certificate.candidate.strategy == "LONG_VOL" and (
            initial <= 0 or replacement <= 0
        ):
            raise ValueError("current debit limits are invalid")
        if certificate.candidate.strategy == "SHORT_VOL" and (
            initial >= 0 or replacement >= 0
        ):
            raise ValueError("current credit limits are invalid")
        return initial, replacement

    async def _close_limit_price(
        self, positions: Sequence[BrokerPosition], now: datetime
    ) -> Decimal:
        checker = self.quote_checker
        assert checker is not None
        symbols = tuple(item.symbol for item in positions)
        if len(symbols) != 4 or len(set(symbols)) != 4:
            raise ValueError("atomic close requires four distinct option positions")
        underlying = self._underlying_from_option_symbol(symbols[0])
        quotes = await checker.get_option_chain(underlying)
        by_symbol = {quote.symbol: quote for quote in quotes}
        if set(symbols) - by_symbol.keys():
            raise ValueError("close quote is missing")
        parent_quantity = self._close_parent_quantity(positions)
        cashflow = Decimal("0")
        for position in positions:
            quote = by_symbol[position.symbol]
            if (
                quote.feed != self.required_feed
                or quote.bid is None
                or quote.ask is None
                or quote.bid > quote.ask
            ):
                raise ValueError("close requires an executable configured-feed bid and ask")
            if (
                quote.observed_at.tzinfo is None
                or quote.observed_at.utcoffset() is None
                or quote.observed_at > now
                or now - quote.observed_at > MAX_QUOTE_AGE
            ):
                raise ValueError("close quote timestamp is invalid or stale")
            leg_ratio = Decimal(abs(position.quantity) // parent_quantity)
            is_long = position_is_long(position)
            cashflow += (quote.ask if not is_long else -quote.bid) * leg_ratio
        self._validate_close_structure(positions, by_symbol)
        if cashflow == 0:
            raise ValueError("close price cannot be zero")
        return cashflow

    @staticmethod
    def _validate_close_structure(
        positions: Sequence[BrokerPosition], quotes: dict[str, OptionQuote]
    ) -> None:
        """Require the broker positions to be one covered-condor inverse."""

        selected = [quotes[position.symbol] for position in positions]
        if len({quote.underlying for quote in selected}) != 1:
            raise ValueError("close requires one underlying")
        if len({quote.expiration for quote in selected}) != 1:
            raise ValueError("close requires one expiration")
        if {quote.right for quote in selected} != {"P", "C"}:
            raise ValueError("close requires put and call legs")
        puts = sorted((quote for quote in selected if quote.right == "P"), key=lambda q: q.strike)
        calls = sorted((quote for quote in selected if quote.right == "C"), key=lambda q: q.strike)
        if (
            len(puts) != 2
            or len(calls) != 2
            or puts[0].strike >= puts[1].strike
            or calls[0].strike >= calls[1].strike
        ):
            raise ValueError("close requires ordered two-by-two condor strikes")
        ordered_symbols = tuple(quote.symbol for quote in (*puts, *calls))
        by_symbol = {position.symbol: position for position in positions}
        sides = tuple(by_symbol[symbol].side.strip().lower() for symbol in ordered_symbols)
        if sides not in {
            ("long", "short", "short", "long"),
            ("short", "long", "long", "short"),
        }:
            raise ValueError("close requires the exact inverse condor side pattern")

    @staticmethod
    def _close_parent_quantity(positions: Sequence[BrokerPosition]) -> int:
        from math import gcd

        quantities = [abs(position.quantity) for position in positions if position.quantity]
        if not quantities:
            raise ValueError("close requires non-zero position quantities")
        return gcd(*quantities)

    @staticmethod
    def _underlying_from_option_symbol(symbol: str) -> AllowedUnderlying:
        allowed: tuple[AllowedUnderlying, ...] = ("SPY", "QQQ", "IWM")
        for underlying in allowed:
            if symbol.startswith(underlying):
                return underlying
        raise ValueError("close position underlying is outside the allowed universe")

    async def _observe(self, order_ids: Sequence[str]) -> _ObservedExecutionState | None:
        try:
            rows: list[BrokerOrder] = []
            for order_id in order_ids:
                rows.append(await self.broker.get_order(order_id))
            positions = await self.broker.get_positions()
            return _ObservedExecutionState(tuple(rows), positions)
        except Exception:
            return None

    async def _cancel_and_observe(
        self,
        certificate: TradeCertificate,
        now: datetime,
        order_ids: list[str],
    ) -> ExecutionRecord:
        return await self._cancel_working_siblings(certificate, now, order_ids, None)

    async def _cancel_working_siblings(
        self,
        certificate: TradeCertificate,
        now: datetime,
        order_ids: list[str],
        observed: _ObservedExecutionState | None,
    ) -> ExecutionRecord:
        """Cancel every still-working sibling before deciding a fill."""

        if observed is None:
            observed = await self._observe(order_ids)
        if observed is None:
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids)
        if not any(self._is_working(row) for row in observed.orders):
            return self._decide(certificate, now, observed, order_ids) or self._record(
                certificate, "RECONCILE_REQUIRED", now, order_ids, observed
            )
        try:
            for row in observed.orders:
                if self._is_working(row):
                    try:
                        await self.broker.cancel_order(row.order_id)
                    except BrokerMutationError:
                        continue
        except Exception:
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids, observed)
        observed = await self._observe(order_ids)
        if observed is None:
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids)
        decision = self._decide(certificate, now, observed, order_ids)
        return decision or self._record(
            certificate, "RECONCILE_REQUIRED", now, order_ids, observed
        )

    def _decide(
        self,
        certificate: TradeCertificate,
        now: datetime,
        observed: _ObservedExecutionState,
        order_ids: list[str],
    ) -> ExecutionRecord | None:
        if any(row.status.upper() not in _KNOWN_ORDER_STATES for row in observed.orders):
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids, observed)
        filled = tuple(row for row in observed.orders if self._is_filled(row))
        partial = tuple(row for row in observed.orders if self._is_partial(row))
        working = tuple(row for row in observed.orders if self._is_working(row))
        if filled and (len(filled) != 1 or partial or working):
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids, observed)
        if filled:
            return self._filled_record(certificate, now, order_ids, observed)
        if partial:
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids, observed)
        rejected = tuple(row for row in observed.orders if self._is_rejected(row))
        canceled = tuple(row for row in observed.orders if self._is_canceled(row))
        if rejected and (working or canceled):
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids, observed)
        if rejected:
            return self._record(certificate, "REJECTED", now, order_ids, observed)
        if canceled and len(canceled) == len(observed.orders):
            return self._record(certificate, "CANCELED", now, order_ids, observed)
        if not working:
            return self._record(certificate, "RECONCILE_REQUIRED", now, order_ids, observed)
        return None

    @staticmethod
    def _is_filled(order: BrokerOrder) -> bool:
        return order.status.upper() in BROKER_FILLED_ORDER_STATES and order.filled_quantity > 0

    @staticmethod
    def _is_partial(order: BrokerOrder) -> bool:
        return order.status.upper() in {"PARTIALLY_FILLED", "PARTIAL_FILLED"}

    @staticmethod
    def _is_rejected(order: BrokerOrder) -> bool:
        return order.status.upper() in BROKER_REJECTED_ORDER_STATES

    @staticmethod
    def _is_canceled(order: BrokerOrder) -> bool:
        return order.status.upper() in BROKER_CANCELED_ORDER_STATES

    @staticmethod
    def _is_working(order: BrokerOrder) -> bool:
        return order.status.upper() in BROKER_ACTIVE_ORDER_STATES

    def _record(
        self,
        certificate: TradeCertificate,
        state: str,
        now: datetime,
        order_ids: Sequence[str] = (),
        observed: _ObservedExecutionState | None = None,
    ) -> ExecutionRecord:
        record = ExecutionRecord(
            case_id=certificate.case_id,
            certificate_id=certificate.certificate_id,
            alpaca_order_ids=tuple(order_ids),
            state=cast(ExecutionState, state),
            submitted_at=now,
            updated_at=now,
            filled_quantity=(
                sum(row.filled_quantity for row in observed.orders) if observed is not None else 0
            ),
        )
        # Pydantic's original record model predates durable deadlines and
        # client ids.  Attach these compatibility attributes so repository
        # projections can persist them while richer models can serialize them.
        object.__setattr__(record, "deadline_at", now + self.cancel_after)
        object.__setattr__(record, "role", "entry")
        object.__setattr__(
            record, "client_order_id", entry_client_order_id(certificate.certificate_id)
        )
        return self._attach_observations(record, observed)

    def _filled_record(
        self,
        certificate: TradeCertificate,
        now: datetime,
        order_ids: Sequence[str],
        observed: _ObservedExecutionState,
    ) -> ExecutionRecord:
        filled = next(row for row in observed.orders if ExecutionService._is_filled(row))
        record = ExecutionRecord(
            case_id=certificate.case_id,
            certificate_id=certificate.certificate_id,
            alpaca_order_ids=tuple(order_ids),
            state="FILLED",
            submitted_at=now,
            updated_at=now,
            filled_quantity=filled.filled_quantity,
            average_fill_price=filled.average_fill_price,
        )
        object.__setattr__(record, "deadline_at", now + self.cancel_after)
        object.__setattr__(record, "role", "entry")
        object.__setattr__(
            record, "client_order_id", entry_client_order_id(certificate.certificate_id)
        )
        return self._attach_observations(record, observed)

    @staticmethod
    def _attach_observations(
        record: ExecutionRecord, observed: _ObservedExecutionState | None
    ) -> ExecutionRecord:
        """Attach broker observations when the richer execution model supports it."""

        # Keep compatibility with the original record shape while allowing
        # the repository to persist every observed order state.  The current
        # domain model predates this field, so retain it as a compatibility
        # attribute for the append-only fallback writer.
        if observed is None:
            return record
        observations: tuple[dict[str, Any], ...] = tuple(
            {
                "order_id": row.order_id,
                "status": row.status,
                "filled_quantity": row.filled_quantity,
                "average_fill_price": row.average_fill_price,
                "role": "entry",
                "signed_quantities": {},
                "deadline_at": getattr(record, "deadline_at", None),
                "client_order_id": getattr(record, "client_order_id", None),
            }
            for row in observed.orders
        )
        object.__setattr__(record, "order_observations", observations)
        fields = getattr(type(record), "model_fields", {})
        if "order_observations" not in fields:
            return record
        updates: dict[str, Any] = {"order_observations": observations}
        if "deadline_at" in fields:
            updates["deadline_at"] = getattr(record, "deadline_at", None)
        if "client_order_id" in fields:
            updates["client_order_id"] = getattr(record, "client_order_id", None)
        if "role" in fields:
            updates["role"] = "entry"
        return record.model_copy(update=updates)
