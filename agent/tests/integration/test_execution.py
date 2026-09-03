"""Paper execution lifecycle tests using a fully offline scripted broker."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from lexguard.adapters.alpaca_trading import (
    BrokerAccount,
    BrokerClock,
    BrokerMutationError,
    BrokerOrder,
    BrokerPosition,
    PaperBroker,
)
from lexguard.domain.hashing import canonical_sha256
from lexguard.domain.models import (
    CandidateStructure,
    OptionLeg,
    OptionQuote,
    TradeCertificate,
)
from lexguard.domain.policy import RiskContext
from lexguard.services.execution import ExecutionService
from lexguard.services.reconciliation import ReconciliationService

NOW = datetime(2026, 8, 24, 14, 10, tzinfo=UTC)
EXPIRATION = date(2026, 8, 25)
CASE_ID = UUID("44444444-4444-4444-4444-444444444444")


def certificate(
    *, issued_at: datetime = NOW, expires_at: datetime | None = None
) -> TradeCertificate:
    candidate = CandidateStructure(
        candidate_id=UUID("11111111-1111-1111-1111-111111111111"),
        strategy="LONG_VOL",
        underlying="SPY",
        expiration=EXPIRATION,
        legs=(
            OptionLeg(
                symbol="SPY260825P00575000",
                underlying="SPY",
                expiration=EXPIRATION,
                strike=Decimal("575"),
                right="P",
                side="SELL",
                ratio=1,
            ),
            OptionLeg(
                symbol="SPY260825P00580000",
                underlying="SPY",
                expiration=EXPIRATION,
                strike=Decimal("580"),
                right="P",
                side="BUY",
                ratio=1,
            ),
            OptionLeg(
                symbol="SPY260825C00590000",
                underlying="SPY",
                expiration=EXPIRATION,
                strike=Decimal("590"),
                right="C",
                side="BUY",
                ratio=1,
            ),
            OptionLeg(
                symbol="SPY260825C00595000",
                underlying="SPY",
                expiration=EXPIRATION,
                strike=Decimal("595"),
                right="C",
                side="SELL",
                ratio=1,
            ),
        ),
        quantity=1,
        entry_limit=Decimal("1.25"),
        max_loss=Decimal("125"),
        modeled_friction=Decimal("0"),
        modeled_fees=Decimal("0"),
        robust_ev=Decimal("25"),
    )
    return TradeCertificate(
        certificate_id=UUID("22222222-2222-2222-2222-222222222222"),
        case_id=CASE_ID,
        candidate=candidate,
        issued_at=issued_at,
        expires_at=expires_at or issued_at + timedelta(minutes=5),
        policy_version="risk.v1",
        proposal_hash=canonical_sha256(candidate),
        account_equity=Decimal("100000"),
        daily_pnl=Decimal("0"),
        competition_drawdown=Decimal("0"),
    )


class ScriptedBroker:
    base_url = "https://paper-api.alpaca.markets"

    def __init__(
        self, *, order_states: list[BrokerOrder], replace_error: Exception | None = None
    ) -> None:
        self.order_states = order_states
        self.replace_error = replace_error
        self.submitted: list[object] = []
        self.submit_count = 0
        self.replace_count = 0
        self.cancel_count = 0
        self.submitted_prices: list[Decimal | None] = []
        self.replaced_prices: list[Decimal] = []
        self.position_reads = 0
        self.order_reads = 0

    async def get_account(self) -> BrokerAccount:
        return BrokerAccount(
            status="ACTIVE",
            equity=Decimal("100000"),
            last_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            competition_drawdown=Decimal("0"),
            options_level=3,
            base_url=self.base_url,
        )

    async def get_positions(self) -> tuple[BrokerPosition, ...]:
        self.position_reads += 1
        return ()

    async def get_orders(self) -> tuple[BrokerOrder, ...]:
        return ()

    async def get_clock(self) -> BrokerClock:
        return BrokerClock(timestamp=NOW, is_open=True)

    async def submit_mleg(
        self, trade_certificate: TradeCertificate, limit_price: Decimal | None = None
    ) -> BrokerOrder:
        self.submit_count += 1
        self.submitted_prices.append(limit_price)
        self.submitted.append(
            PaperBroker.build_mleg_request(trade_certificate, limit_price=limit_price)
        )
        return BrokerOrder(
            order_id="order-1", status="new", filled_quantity=0, average_fill_price=None
        )

    async def get_order(self, order_id: str) -> BrokerOrder:
        self.order_reads += 1
        if not self.order_states:
            return BrokerOrder(order_id=order_id, status="unknown")
        state = self.order_states.pop(0)
        return state.model_copy(update={"order_id": order_id})

    async def replace_order(self, order_id: str, limit_price: Decimal) -> BrokerOrder:
        self.replace_count += 1
        self.replaced_prices.append(limit_price)
        if self.replace_error is not None:
            raise self.replace_error
        return BrokerOrder(
            order_id="order-2", status="new", filled_quantity=0, average_fill_price=None
        )

    async def cancel_order(self, order_id: str) -> None:
        self.cancel_count += 1


class QuoteSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []

    async def get_option_chain(
        self,
        underlying_symbol: str,
        *,
        expiration_date: date | str | None = None,
        limit: int = 100,
    ) -> tuple[OptionQuote, ...]:
        if expiration_date is not None:
            assert isinstance(expiration_date, date)
            self.calls.append((underlying_symbol, expiration_date))
        return tuple(
            OptionQuote(
                symbol=leg.symbol,
                underlying="SPY",
                expiration=EXPIRATION,
                strike=leg.strike,
                right=leg.right,
                bid=Decimal("0.40") if leg.side == "SELL" else Decimal("1.00"),
                ask=Decimal("0.50") if leg.side == "SELL" else Decimal("1.10"),
                last=None,
                open_interest=100,
                implied_volatility=Decimal("0.2"),
                observed_at=NOW,
                feed="opra",
            )
            for leg in certificate().candidate.legs
        )


class AllowingRiskProvider:
    async def build(self, trade_certificate, now, account, positions, orders, clock, quotes):  # type: ignore[no-untyped-def]
        return RiskContext(
            now=now,
            decision_window="10:05",
            evidence_observed_at=now,
            daily_pnl=Decimal("0"),
            competition_drawdown=Decimal("0"),
            entries_today=0,
            traded_symbols_today=(),
            open_structure_count=0,
            open_order_count=0,
            open_position_count=0,
            account_status="ACTIVE",
            options_level=3,
            opra_available=all(quote.feed == "opra" for quote in quotes),
            base_url=account.base_url,
        )


def execution_service(broker: ScriptedBroker, quotes: QuoteSpy | None = None) -> ExecutionService:
    return ExecutionService(
        broker,
        quote_checker=quotes or QuoteSpy(),
        risk_context_provider=AllowingRiskProvider(),
    )


@pytest.mark.asyncio
async def test_fill_during_replace_is_reconciled_without_duplicate() -> None:
    broker = ScriptedBroker(
        order_states=[
            BrokerOrder(order_id="order-1", status="new"),
            BrokerOrder(
                order_id="order-1",
                status="filled",
                filled_quantity=1,
                average_fill_price=Decimal("1.20"),
            ),
        ],
        replace_error=BrokerMutationError("already filled"),
    )

    result = await execution_service(broker).execute(certificate(), NOW)

    assert result.state == "FILLED"
    assert broker.submit_count == 1
    assert broker.replace_count == 1
    assert result.alpaca_order_ids == ("order-1",)
    assert broker.position_reads >= 2


@pytest.mark.asyncio
async def test_partial_fill_is_halted_for_reconciliation() -> None:
    broker = ScriptedBroker(
        order_states=[BrokerOrder(order_id="order-1", status="partially_filled", filled_quantity=1)]
    )

    result = await execution_service(broker).execute(certificate(), NOW)

    assert result.state == "RECONCILE_REQUIRED"
    assert broker.submit_count == 1
    assert broker.replace_count == 0


@pytest.mark.asyncio
async def test_entry_client_lookup_uses_all_status_endpoint() -> None:
    class AllStatusBroker(ScriptedBroker):
        def __init__(self) -> None:
            super().__init__(order_states=[])
            self.lookup_calls: list[str] = []

        async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder:
            self.lookup_calls.append(client_order_id)
            return BrokerOrder(
                order_id="historical-order",
                status="canceled",
                client_order_id=client_order_id,
            )

        async def get_orders(self) -> tuple[BrokerOrder, ...]:
            raise AssertionError("open-order listing must not be used for client lookup")

    broker = AllStatusBroker()
    service = execution_service(broker)

    result = await service._find_client_order("lexguard-entry-test")

    assert result == ["historical-order"]
    assert broker.lookup_calls == ["lexguard-entry-test"]


@pytest.mark.asyncio
async def test_unclaimed_persisted_entry_intent_never_mutates_broker() -> None:
    class UnclaimedIntentRepository:
        def create_or_claim_entry_intent(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                claimed=False,
                record=SimpleNamespace(order_ids=("persisted-order",)),
            )

    broker = ScriptedBroker(
        order_states=[BrokerOrder(order_id="persisted-order", status="new")]
    )
    issued = NOW - timedelta(seconds=120)
    service = ExecutionService(
        broker,
        quote_checker=QuoteSpy(),
        risk_context_provider=AllowingRiskProvider(),
        repository=UnclaimedIntentRepository(),
    )

    result = await service.execute(certificate(issued_at=issued), NOW)

    assert result.state == "RECONCILE_REQUIRED"
    assert result.alpaca_order_ids == ("persisted-order",)
    assert broker.submit_count == 0
    assert broker.replace_count == 0
    assert broker.cancel_count == 0


@pytest.mark.asyncio
async def test_cancel_race_records_fill_and_never_duplicates() -> None:
    # The cancel ladder is deadline-driven through durable chains: a working
    # order past its submission deadline is canceled, and a fill that lands
    # during the cancel is recorded exactly once with no resubmission.
    class ExpiredChainRepository:
        def active_entry_order_chains(self):  # type: ignore[no-untyped-def]
            return (
                {
                    "certificate": certificate().model_dump(mode="json"),
                    "order_ids": ("order-1",),
                    "deadline_at": (NOW - timedelta(seconds=1)).isoformat(),
                },
            )

    broker = ScriptedBroker(
        order_states=[
            BrokerOrder(order_id="order-1", status="new"),
            BrokerOrder(
                order_id="order-1",
                status="filled",
                filled_quantity=1,
                average_fill_price=Decimal("1.22"),
            ),
        ]
    )

    results = await ExecutionService(
        broker,
        repository=ExpiredChainRepository(),
    ).reconcile_entry_orders(NOW)

    assert results[0].state == "FILLED"
    assert broker.cancel_count == 1
    assert broker.submit_count == 0


@pytest.mark.asyncio
async def test_stale_certificate_submission_is_not_insta_canceled() -> None:
    # Regression: the ladder was once anchored to certificate issuance, so an
    # order submitted five minutes after evaluation was canceled immediately.
    issued = NOW - timedelta(minutes=5)
    broker = ScriptedBroker(
        order_states=[
            BrokerOrder(order_id="order-1", status="new"),
            BrokerOrder(order_id="order-1", status="replaced"),
            BrokerOrder(order_id="order-2", status="new"),
        ]
    )

    result = await execution_service(broker).execute(
        certificate(issued_at=issued, expires_at=NOW + timedelta(minutes=5)), NOW
    )

    assert result.state == "REPLACED"
    assert broker.cancel_count == 0
    assert broker.submit_count == 1
    assert result.deadline_at == NOW + timedelta(seconds=90)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_expired_certificate_and_live_endpoint_are_rejected_before_submit() -> None:
    expired_broker = ScriptedBroker(order_states=[])
    expired = await execution_service(expired_broker).execute(
        certificate(
            issued_at=NOW - timedelta(minutes=5),
            expires_at=NOW - timedelta(seconds=1),
        ),
        NOW,
    )
    assert expired.state == "REJECTED"
    assert expired_broker.submit_count == 0

    live_broker = ScriptedBroker(order_states=[])
    live_broker.base_url = "https://api.alpaca.markets"
    live = await execution_service(live_broker).execute(certificate(), NOW)
    assert live.state == "REJECTED"
    assert live_broker.submit_count == 0


@pytest.mark.asyncio
async def test_missing_broker_risk_fields_block_execution_before_submit() -> None:
    broker = ScriptedBroker(order_states=[])
    broker.get_account = lambda: _missing_account()  # type: ignore[method-assign]

    result = await execution_service(broker).execute(certificate(), NOW)

    assert result.state == "RECONCILE_REQUIRED"
    assert broker.submit_count == 0


async def _missing_account() -> BrokerAccount:
    return BrokerAccount(
        status="ACTIVE",
        equity=Decimal("100000"),
        base_url="https://paper-api.alpaca.markets",
    )


@pytest.mark.asyncio
async def test_execution_refreshes_all_certified_quotes_before_submit() -> None:
    broker = ScriptedBroker(
        order_states=[BrokerOrder(order_id="order-1", status="filled", filled_quantity=1)]
    )
    quotes = QuoteSpy()

    result = await execution_service(broker, quotes).execute(certificate(), NOW)

    assert result.state == "FILLED"
    assert quotes.calls == [("SPY", EXPIRATION)]


@pytest.mark.asyncio
async def test_execution_uses_current_midpoint_then_bounded_executable_replacement() -> None:
    broker = ScriptedBroker(
        order_states=[BrokerOrder(order_id="order-1", status="new")] * 2
    )

    result = await execution_service(broker).execute(certificate(), NOW)

    # The replacement observation includes an unknown sibling state.  The
    # fail-closed lifecycle must require reconciliation rather than project a
    # successful replacement from incomplete broker truth.
    assert result.state == "RECONCILE_REQUIRED"
    assert broker.submitted_prices == [Decimal("1.20")]
    assert broker.replaced_prices == [Decimal("1.25")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "post_replace_states",
    [
        [
            BrokerOrder(order_id="order-1", status="filled", filled_quantity=1),
            BrokerOrder(order_id="order-2", status="new"),
        ],
        [
            BrokerOrder(order_id="order-1", status="partially_filled", filled_quantity=1),
            BrokerOrder(order_id="order-2", status="new"),
        ],
        [
            BrokerOrder(order_id="order-1", status="new"),
            BrokerOrder(order_id="order-2", status="unknown"),
        ],
    ],
)
async def test_post_replace_sibling_observations_never_project_replaced(
    post_replace_states: list[BrokerOrder],
) -> None:
    broker = ScriptedBroker(
        order_states=[BrokerOrder(order_id="order-1", status="new"), *post_replace_states]
    )

    result = await execution_service(broker).execute(certificate(), NOW)

    assert result.state == "RECONCILE_REQUIRED"


@pytest.mark.asyncio
async def test_stale_current_opra_quote_blocks_submission() -> None:
    class StaleQuoteSpy(QuoteSpy):
        async def get_option_chain(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return tuple(
                quote.model_copy(update={"observed_at": NOW - timedelta(minutes=2)})
                for quote in await super().get_option_chain(*args, **kwargs)
            )

    broker = ScriptedBroker(order_states=[])

    result = await execution_service(broker, StaleQuoteSpy()).execute(certificate(), NOW)

    assert result.state == "RECONCILE_REQUIRED"
    assert broker.submit_count == 0


@pytest.mark.asyncio
async def test_refreshed_quote_contract_identity_must_match_certificate() -> None:
    class WrongContractQuotes(QuoteSpy):
        async def get_option_chain(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            quotes = await super().get_option_chain(*args, **kwargs)
            return (quotes[0].model_copy(update={"strike": Decimal("576")}), *quotes[1:])

    broker = ScriptedBroker(order_states=[])

    result = await execution_service(broker, WrongContractQuotes()).execute(certificate(), NOW)

    assert result.state == "RECONCILE_REQUIRED"
    assert broker.submit_count == 0


@pytest.mark.asyncio
async def test_close_uses_quote_derived_per_parent_price_for_unequal_positions() -> None:
    class CloseBroker(ScriptedBroker):
        def __init__(self) -> None:
            super().__init__(
                order_states=[BrokerOrder(order_id="close-1", status="FILLED", filled_quantity=1)]
            )
            self.closed: tuple[tuple[BrokerPosition, ...], Decimal] | None = None

        async def submit_close_mleg(self, positions, *, limit_price):  # type: ignore[no-untyped-def]
            self.closed = (tuple(positions), limit_price)
            return BrokerOrder(order_id="close-1", status="new")

        async def get_positions(self) -> tuple[BrokerPosition, ...]:
            return (BrokerPosition(symbol="IWM260825P00100000", quantity=1, side="long"),)

    broker = CloseBroker()
    positions = tuple(
        BrokerPosition(symbol=leg.symbol, quantity=quantity, side=side)
        for leg, quantity, side in zip(
            certificate().candidate.legs,
            (2, 4, 2, 4),
            ("long", "short", "short", "long"),
            strict=True,
        )
    )

    result = await ExecutionService(broker, quote_checker=QuoteSpy()).close(
        positions, "TIME_EXIT", NOW
    )

    assert result.order_id == "close-1"
    assert result.state == "CLOSED"
    assert broker.closed is not None
    assert broker.closed[1] == Decimal("2.10")


@pytest.mark.asyncio
async def test_close_recovers_all_status_client_order_before_resubmit() -> None:
    class RecoveringCloseBroker(ScriptedBroker):
        def __init__(self) -> None:
            super().__init__(
                order_states=[BrokerOrder(order_id="close-existing", status="CANCELED")]
            )
            self.lookup_calls: list[str] = []
            self.close_submits = 0

        async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder:
            self.lookup_calls.append(client_order_id)
            return BrokerOrder(
                order_id="close-existing",
                status="CANCELED",
                client_order_id=client_order_id,
            )

        async def submit_close_mleg(
            self, positions, *, limit_price, client_order_id=None  # type: ignore[no-untyped-def]
        ) -> BrokerOrder:
            self.close_submits += 1
            return BrokerOrder(order_id="unexpected", status="new")

        async def get_positions(self) -> tuple[BrokerPosition, ...]:
            return ()

    broker = RecoveringCloseBroker()
    positions = tuple(
        BrokerPosition(symbol=leg.symbol, quantity=1, side=side)
        for leg, side in zip(
            certificate().candidate.legs,
            ("long", "short", "short", "long"),
            strict=True,
        )
    )

    result = await ExecutionService(broker, quote_checker=QuoteSpy()).close(
        positions, "TIME_EXIT", NOW
    )

    assert result.state == "REJECTED"
    assert len(broker.lookup_calls) == 1
    assert broker.close_submits == 0


@pytest.mark.asyncio
async def test_restart_close_intent_recovers_missing_order_id_and_cas_persists_it() -> None:
    class RestartCloseBroker(ScriptedBroker):
        def __init__(self) -> None:
            super().__init__(
                order_states=[
                    BrokerOrder(
                        order_id="close-recovered", status="FILLED", filled_quantity=1
                    )
                ]
            )
            self.lookup_calls: list[str] = []

        async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder:
            self.lookup_calls.append(client_order_id)
            return BrokerOrder(
                order_id="close-recovered",
                status="FILLED",
                filled_quantity=1,
                client_order_id=client_order_id,
            )

        async def get_positions(self) -> tuple[BrokerPosition, ...]:
            return ()

    class RestartCloseIntentRepository:
        def __init__(self) -> None:
            self.updates: list[tuple[str, str, str | None]] = []

        def active_close_intents(self):  # type: ignore[no-untyped-def]
            return (
                SimpleNamespace(
                    intent_key="close-intent",
                    order_id=None,
                    symbols=tuple(leg.symbol for leg in certificate().candidate.legs),
                    reason="TIME_EXIT",
                    case_id=None,
                    claim_token=None,
                    client_order_id="lexguard-close-restart",
                    signed_quantities={},
                ),
            )

        def update_close_intent(
            self,
            intent_key: str,
            *,
            state: str,
            order_id: str | None = None,
            now=None,
            claim_token: str | None = None,
        ):  # type: ignore[no-untyped-def]
            self.updates.append((state, order_id or "", claim_token))

    broker = RestartCloseBroker()
    repository = RestartCloseIntentRepository()
    result = await ExecutionService(
        broker,
        quote_checker=QuoteSpy(),
        close_intent_repository=repository,
    ).reconcile_close_intents(NOW)

    assert result[0].state == "CLOSED"
    assert broker.lookup_calls == ["lexguard-close-restart"]
    assert any(order_id == "close-recovered" for _, order_id, _ in repository.updates)


@pytest.mark.asyncio
async def test_restart_close_intent_ambiguity_stays_reconcile_required() -> None:
    class AmbiguousBroker(ScriptedBroker):
        async def get_order_by_client_id(self, client_order_id: str) -> tuple[BrokerOrder, ...]:
            return (
                BrokerOrder(order_id="close-1", status="CANCELED", client_order_id=client_order_id),
                BrokerOrder(order_id="close-2", status="REJECTED", client_order_id=client_order_id),
            )

    class Repository:
        def __init__(self) -> None:
            self.updates = 0

        def active_close_intents(self):  # type: ignore[no-untyped-def]
            return (
                SimpleNamespace(
                    intent_key="ambiguous-close",
                    order_id=None,
                    symbols=tuple(leg.symbol for leg in certificate().candidate.legs),
                    reason="TIME_EXIT",
                    case_id=None,
                    claim_token=None,
                    client_order_id="lexguard-close-ambiguous",
                    signed_quantities={},
                ),
            )

        def update_close_intent(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.updates += 1

    repository = Repository()
    result = await ExecutionService(
        AmbiguousBroker(order_states=[]),
        close_intent_repository=repository,
    ).reconcile_close_intents(NOW)

    assert result[0].state == "RECONCILE_REQUIRED"
    assert repository.updates == 0


@pytest.mark.asyncio
async def test_restart_entry_without_deadline_cancels_working_order() -> None:
    class RestartRepository:
        def active_entry_order_chains(self):  # type: ignore[no-untyped-def]
            return (
                {
                    "certificate": certificate().model_dump(mode="json"),
                    "order_ids": ("order-1",),
                    "deadline_at": None,
                },
            )

    broker = ScriptedBroker(order_states=[BrokerOrder(order_id="order-1", status="new")])
    result = await ExecutionService(
        broker,
        repository=RestartRepository(),
    ).reconcile_entry_orders(NOW)

    assert result[0].state == "RECONCILE_REQUIRED"
    assert broker.cancel_count == 1


@pytest.mark.asyncio
async def test_close_rejects_stale_quote_timestamp_before_submit() -> None:
    class StaleCloseBroker(ScriptedBroker):
        def __init__(self) -> None:
            super().__init__(order_states=[])
            self.submits = 0

        async def submit_close_mleg(self, positions, *, limit_price):  # type: ignore[no-untyped-def]
            self.submits += 1
            return BrokerOrder(order_id="close-1", status="new")

    class StaleCloseQuotes(QuoteSpy):
        async def get_option_chain(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            quotes = await super().get_option_chain(*args, **kwargs)
            return tuple(
                quote.model_copy(update={"observed_at": NOW - timedelta(seconds=31)})
                for quote in quotes
            )

    broker = StaleCloseBroker()
    positions = tuple(
        BrokerPosition(symbol=leg.symbol, quantity=1, side="long")
        for leg in certificate().candidate.legs
    )

    with pytest.raises(ValueError, match="timestamp"):
        await ExecutionService(broker, quote_checker=StaleCloseQuotes()).close(
            positions, "TIME_EXIT", NOW
        )
    assert broker.submits == 0


@pytest.mark.asyncio
async def test_reconciliation_halts_unknown_broker_order_and_matches_clean_restart() -> None:
    class RestartBroker(ScriptedBroker):
        def __init__(self) -> None:
            super().__init__(order_states=[])
            self.orders = (BrokerOrder(order_id="order-1", status="new"),)
            self.positions = (BrokerPosition(symbol="SPY260825P00580000", quantity=1, side="long"),)

        async def get_orders(self) -> tuple[BrokerOrder, ...]:
            return self.orders

        async def get_positions(self) -> tuple[BrokerPosition, ...]:
            return self.positions

    mismatch = await ReconciliationService(RestartBroker()).reconcile()
    assert mismatch.state == "RECONCILE_REQUIRED"
    assert mismatch.reason_codes == ("UNKNOWN_BROKER_ORDER", "UNKNOWN_BROKER_POSITION")

    consistent = await ReconciliationService(
        RestartBroker(),
        ledger_order_ids=("order-1",),
        ledger_position_symbols=("SPY260825P00580000",),
    ).reconcile()
    assert consistent.state == "CONSISTENT"
    assert consistent.reason_codes == ()
