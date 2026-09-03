"""Deterministic candidate enumeration and ranking tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from lexguard.domain.enums import Scenario
from lexguard.domain.models import (
    AccountSnapshot,
    ForecastDistribution,
    ForecastNode,
    MarketEvidence,
    OptionQuote,
    UnderlyingBar,
)
from lexguard.domain.payoff import exact_max_loss, structure_pnl
from lexguard.services.candidates import BOTH, CandidateService, rank_candidates

OBSERVED = datetime(2026, 8, 24, 14, 5, tzinfo=UTC)
EXPIRATION = date(2026, 8, 25)


def _quote(strike: str, right: str, *, bid: str = "1.00", ask: str = "1.20") -> OptionQuote:
    strike_decimal = Decimal(strike)
    encoded = int(strike_decimal * Decimal("1000"))
    symbol = f"SPY{EXPIRATION:%y%m%d}{right}{encoded:08d}"
    return OptionQuote(
        symbol=symbol,
        underlying="SPY",
        expiration=EXPIRATION,
        strike=strike_decimal,
        right=right,
        bid=Decimal(bid),
        ask=Decimal(ask),
        last=Decimal(bid),
        open_interest=1000,
        implied_volatility=Decimal("0.20"),
        observed_at=OBSERVED,
        feed="opra",
    )


def _evidence(
    quotes: tuple[OptionQuote, ...], *, validate: bool = True
) -> MarketEvidence:
    evidence = {
        "case_id": UUID("22222222-2222-2222-2222-222222222222"),
        "observed_at": OBSERVED,
        "decision_window": "10:05",
        "underlying": "SPY",
        "underlying_bars": (
            UnderlyingBar(
                symbol="SPY",
                timestamp=OBSERVED,
                open=Decimal("590"),
                high=Decimal("591"),
                low=Decimal("589"),
                close=Decimal("590"),
                volume=10000,
            ),
        ),
        "option_quotes": quotes,
        "news": (),
        "account_snapshot": AccountSnapshot(
            observed_at=OBSERVED,
            status="ACTIVE",
            equity=Decimal("100000"),
            buying_power=Decimal("100000"),
            daily_pnl=Decimal("0"),
            competition_drawdown=Decimal("0"),
            options_level=3,
            opra_available=True,
            base_url="https://paper-api.alpaca.markets",
        ),
        "source": "alpaca_mcp",
        "content_hash": "evidence",
    }
    return MarketEvidence(**evidence) if validate else MarketEvidence.model_construct(**evidence)


def _distribution() -> ForecastDistribution:
    return ForecastDistribution(
        nodes=(
            ForecastNode(return_value=Decimal("-0.03"), probability=Decimal("0.25")),
            ForecastNode(return_value=Decimal("0"), probability=Decimal("0.50")),
            ForecastNode(return_value=Decimal("0.03"), probability=Decimal("0.25")),
        ),
        calibrated_at=OBSERVED,
        training_end=datetime(2026, 8, 23, 20, tzinfo=UTC),
        artifact_hash="forecast",
    )


@pytest.fixture
def chain() -> tuple[OptionQuote, ...]:
    return (
        _quote("575", "P", bid="2.00", ask="2.10"),
        _quote("580", "P", bid="3.00", ask="3.10"),
        _quote("590", "C", bid="2.50", ask="2.60"),
        _quote("595", "C", bid="1.50", ask="1.60"),
    )


def test_generate_bounded_long_and_short_structures(chain: tuple[OptionQuote, ...]) -> None:
    service = CandidateService(portfolio_capacity=2)
    candidates = service.generate(_evidence(chain), _distribution(), BOTH)

    assert {candidate.strategy for candidate in candidates} == {"LONG_VOL", "SHORT_VOL"}
    assert all(len(candidate.legs) == 4 for candidate in candidates)
    assert all(candidate.quantity >= 1 for candidate in candidates)
    assert all(candidate.max_loss <= Decimal("1000") for candidate in candidates)
    assert all(
        candidate.entry_limit > 0 for candidate in candidates if candidate.strategy == "LONG_VOL"
    )
    assert all(
        candidate.entry_limit < 0 for candidate in candidates if candidate.strategy == "SHORT_VOL"
    )


@pytest.mark.parametrize(
    "replacement",
    [
        {"bid": None},
        {"ask": None},
        {"bid": Decimal("2.00"), "ask": Decimal("1.00")},
        {"open_interest": 0},
        {"feed": "indicative"},
    ],
)
def test_crossed_missing_or_non_opra_quotes_are_removed(
    chain: tuple[OptionQuote, ...], replacement: dict[str, object]
) -> None:
    invalid = (
        OptionQuote.model_construct(**(chain[0].model_dump(mode="python") | replacement))
        if replacement.get("ask") == Decimal("1.00")
        else chain[0].model_copy(update=replacement)
    )
    candidates = CandidateService().generate(
        _evidence((invalid, *chain[1:]), validate=False), _distribution(), BOTH
    )

    assert candidates == ()


def test_dte_and_quote_width_filters_are_fail_closed(chain: tuple[OptionQuote, ...]) -> None:
    too_wide = chain[0].model_copy(update={"ask": Decimal("2.50")})
    service = CandidateService(max_quote_width=Decimal("0.20"))
    assert service.generate(_evidence((too_wide, *chain[1:])), _distribution(), BOTH) == ()

    next_week = chain[0].model_copy(
        update={"expiration": date(2026, 8, 28), "symbol": "SPY260828P00575000"}
    )
    assert service.generate(_evidence((next_week, *chain[1:])), _distribution(), BOTH) == ()


def test_stale_or_future_quotes_are_removed(chain: tuple[OptionQuote, ...]) -> None:
    stale = chain[0].model_copy(update={"observed_at": OBSERVED - timedelta(seconds=121)})
    future = chain[0].model_copy(update={"observed_at": OBSERVED + timedelta(seconds=1)})
    service = CandidateService()

    assert service.generate(_evidence((stale, *chain[1:])), _distribution(), BOTH) == ()
    assert service.generate(_evidence((future, *chain[1:])), _distribution(), BOTH) == ()


@pytest.mark.parametrize(
    "observed_at",
    [OBSERVED - timedelta(seconds=120), OBSERVED],
)
def test_quote_at_freshness_boundary_is_eligible(
    chain: tuple[OptionQuote, ...], observed_at: datetime
) -> None:
    boundary = chain[0].model_copy(update={"observed_at": observed_at})

    candidates = CandidateService().generate(
        _evidence((boundary, *chain[1:])), _distribution(), BOTH
    )

    assert candidates


def test_catalyst_scenario_changes_candidate_evaluation(
    chain: tuple[OptionQuote, ...],
) -> None:
    service = CandidateService(portfolio_capacity=1)
    base = service.generate(_evidence(chain), _distribution(), "LONG_VOL", Scenario.BASE)[0]
    vol_down = service.generate(_evidence(chain), _distribution(), "LONG_VOL", Scenario.VOL_DOWN)[0]

    assert vol_down.robust_ev != base.robust_ev


def test_robust_ev_is_no_greater_than_each_admissible_expected_value(
    chain: tuple[OptionQuote, ...],
) -> None:
    service = CandidateService(portfolio_capacity=1)
    candidate = service.generate(_evidence(chain), _distribution(), {"LONG_VOL"})[0]
    expected_values = []
    for distribution in service.admissible_distributions(_distribution()):
        expected_values.append(
            sum(
                (
                    structure_pnl(
                        candidate,
                        max(
                            Decimal("0"),
                            Decimal("590") * (Decimal("1") + node.return_value),
                        ),
                    )
                    * node.probability
                    for node in distribution.nodes
                ),
                Decimal("0"),
            )
        )

    assert candidate.robust_ev == min(expected_values)
    assert exact_max_loss(candidate) == candidate.max_loss


def test_ranking_is_stable_for_input_order(chain: tuple[OptionQuote, ...]) -> None:
    candidates = CandidateService(portfolio_capacity=1).generate(
        _evidence(chain), _distribution(), BOTH
    )

    assert rank_candidates(tuple(reversed(candidates))) == rank_candidates(candidates)
