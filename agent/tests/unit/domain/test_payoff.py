from datetime import date
from decimal import Decimal
from uuid import uuid4

from hypothesis import given
from hypothesis import strategies as st

from lexguard.domain.models import CandidateStructure, OptionLeg
from lexguard.domain.payoff import exact_max_loss, leg_payoff, structure_pnl

EXPIRATION = date(2026, 8, 25)


def make_leg(symbol: str, strike: str, right: str, side: str) -> OptionLeg:
    return OptionLeg(
        symbol=symbol,
        underlying="SPY",
        expiration=EXPIRATION,
        strike=Decimal(strike),
        right=right,
        side=side,
        ratio=1,
    )


def long_candidate() -> CandidateStructure:
    return CandidateStructure(
        candidate_id=uuid4(),
        strategy="LONG_VOL",
        underlying="SPY",
        expiration=EXPIRATION,
        legs=(
            make_leg("SPY260825P00575000", "575", "P", "SELL"),
            make_leg("SPY260825P00580000", "580", "P", "BUY"),
            make_leg("SPY260825C00590000", "590", "C", "BUY"),
            make_leg("SPY260825C00595000", "595", "C", "SELL"),
        ),
        quantity=1,
        entry_limit=Decimal("1.00"),
        max_loss=Decimal("500"),
        modeled_friction=Decimal("2"),
        modeled_fees=Decimal("1"),
        robust_ev=Decimal("12.50"),
    )


def short_candidate() -> CandidateStructure:
    candidate = long_candidate()
    return candidate.model_copy(
        update={
            "strategy": "SHORT_VOL",
            "entry_limit": Decimal("-1.00"),
            "legs": (
                make_leg("SPY260825P00575000", "575", "P", "BUY"),
                make_leg("SPY260825P00580000", "580", "P", "SELL"),
                make_leg("SPY260825C00590000", "590", "C", "SELL"),
                make_leg("SPY260825C00595000", "595", "C", "BUY"),
            ),
        }
    )


def test_signed_option_payoff_uses_right_and_side() -> None:
    assert leg_payoff(make_leg("SPY260825C00575000", "575", "C", "BUY"), Decimal("580")) == Decimal(
        "500"
    )
    assert leg_payoff(
        make_leg("SPY260825P00575000", "575", "P", "SELL"), Decimal("570")
    ) == Decimal("-500")


@given(st.decimals(min_value="1", max_value="2000", places=2))
def test_max_loss_bounds_every_terminal_payoff(
    terminal: Decimal,
) -> None:
    candidate = long_candidate()
    assert structure_pnl(candidate, terminal) >= -exact_max_loss(candidate)


def test_exact_max_loss_accounts_for_debit_and_fees() -> None:
    assert exact_max_loss(long_candidate()) == Decimal("103")
    assert exact_max_loss(short_candidate()) == Decimal("403")


def test_structure_pnl_uses_credit_as_positive_opening_cashflow() -> None:
    assert structure_pnl(short_candidate(), Decimal("582")) == Decimal("97")
