"""Deterministic, signed option payoff calculations."""

from decimal import Decimal

from .models import CandidateStructure, OptionLeg

CONTRACT_MULTIPLIER = Decimal("100")


def leg_payoff(leg: OptionLeg, terminal_price: Decimal) -> Decimal:
    """Return the signed terminal value of one option leg in dollars."""

    if terminal_price < 0:
        raise ValueError("terminal price cannot be negative")

    if leg.right == "C":
        intrinsic = max(terminal_price - leg.strike, Decimal("0"))
    else:
        intrinsic = max(leg.strike - terminal_price, Decimal("0"))

    direction = Decimal("1") if leg.side == "BUY" else Decimal("-1")
    return intrinsic * CONTRACT_MULTIPLIER * direction * leg.ratio


def structure_pnl(candidate: CandidateStructure, terminal_price: Decimal) -> Decimal:
    """Return terminal P&L including opening cash flow, friction, and fees."""

    terminal_value = sum(
        (leg_payoff(leg, terminal_price) for leg in candidate.legs),
        Decimal("0"),
    )
    opening_cash_flow = -candidate.entry_limit * CONTRACT_MULTIPLIER * candidate.quantity
    costs = (candidate.modeled_friction + candidate.modeled_fees) * candidate.quantity
    return terminal_value * candidate.quantity + opening_cash_flow - costs


def exact_max_loss(candidate: CandidateStructure) -> Decimal:
    """Evaluate the finite payoff breakpoints and return the worst loss."""

    strikes = [leg.strike for leg in candidate.legs]
    max_strike = max(strikes)
    max_width = max(strikes) - min(strikes)
    terminal_prices = {Decimal("0"), *strikes, max_strike + max(max_width, Decimal("1"))}
    minimum_pnl = min(structure_pnl(candidate, price) for price in terminal_prices)
    return max(Decimal("0"), -minimum_pnl)
