"""Finite, quote-driven enumeration of bounded four-leg option structures."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import cast
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from lexguard.domain.enums import Scenario, Strategy
from lexguard.domain.models import (
    CandidateStructure,
    ForecastDistribution,
    MarketEvidence,
    OptionLeg,
    OptionQuote,
    OrderSide,
)
from lexguard.domain.payoff import exact_max_loss, structure_pnl
from lexguard.research.forecast import apply_scenario

BOTH = frozenset({Strategy.LONG_VOL.value, Strategy.SHORT_VOL.value})
_NEW_YORK = ZoneInfo("America/New_York")
MAX_QUOTE_AGE = timedelta(seconds=120)


class CandidateService:
    """Generate only liquid, same-expiration, covered condor structures."""

    def __init__(
        self,
        *,
        max_quote_width: Decimal = Decimal("0.20"),
        portfolio_capacity: int = 1,
        risk_budget: Decimal = Decimal("1000"),
        friction_fraction: Decimal = Decimal("0.50"),
        fee_per_leg: Decimal = Decimal("0.65"),
        required_feed: str = "opra",
    ) -> None:
        if max_quote_width <= 0:
            raise ValueError("max_quote_width must be positive")
        if portfolio_capacity < 0:
            raise ValueError("portfolio_capacity must be non-negative")
        if risk_budget <= 0 or friction_fraction < 0 or fee_per_leg < 0:
            raise ValueError("candidate costs and risk budget are invalid")
        if required_feed not in {"opra", "indicative"}:
            raise ValueError("required_feed must be opra or indicative")
        self.max_quote_width = max_quote_width
        self.portfolio_capacity = portfolio_capacity
        self.risk_budget = risk_budget
        self.friction_fraction = friction_fraction
        self.fee_per_leg = fee_per_leg
        self.required_feed = required_feed

    def generate(
        self,
        evidence: MarketEvidence,
        distribution: ForecastDistribution,
        allowed_sides: Iterable[str] | str,
        scenario: Scenario | str = Scenario.BASE,
    ) -> tuple[CandidateStructure, ...]:
        strategies = _normalize_strategies(allowed_sides)
        catalyst_scenario = _normalize_scenario(scenario)
        if (
            not strategies
            or self.portfolio_capacity == 0
            or not evidence.underlying_bars
            or catalyst_scenario == Scenario.VETO
        ):
            return ()
        current_price = evidence.underlying_bars[-1].close
        evaluation_distribution = apply_scenario(distribution, catalyst_scenario)
        grouped = self._eligible_quotes(evidence)
        candidates: list[CandidateStructure] = []
        for expiration, quotes in grouped.items():
            puts = sorted((quote for quote in quotes if quote.right == "P"), key=lambda q: q.strike)
            calls = sorted(
                (quote for quote in quotes if quote.right == "C"),
                key=lambda q: q.strike,
            )
            for put_outer, put_inner in _pairs(puts):
                for call_inner, call_outer in _pairs(calls):
                    ordered = (
                        put_outer.strike < put_inner.strike < call_inner.strike < call_outer.strike
                    )
                    if not ordered:
                        continue
                    for strategy in strategies:
                        candidate = self._build_candidate(
                            evidence,
                            evaluation_distribution,
                            current_price,
                            expiration,
                            (put_outer, put_inner, call_inner, call_outer),
                            strategy,
                        )
                        if candidate is not None:
                            candidates.append(candidate)
        return rank_candidates(candidates)

    def admissible_distributions(
        self, distribution: ForecastDistribution
    ) -> tuple[ForecastDistribution, ...]:
        return (
            distribution,
            apply_scenario(distribution, Scenario.VOL_UP),
            apply_scenario(distribution, Scenario.VOL_DOWN),
            apply_scenario(distribution, Scenario.LEFT_TAIL),
            apply_scenario(distribution, Scenario.RIGHT_TAIL),
        )

    def _eligible_quotes(self, evidence: MarketEvidence) -> dict[date, tuple[OptionQuote, ...]]:
        observed_date = evidence.observed_at.astimezone(_NEW_YORK).date()
        grouped: dict[date, list[OptionQuote]] = {}
        for quote in evidence.option_quotes:
            if quote.underlying != evidence.underlying:
                continue
            dte = (quote.expiration - observed_date).days
            if dte not in {1, 2, 3}:
                continue
            if quote.feed != self.required_feed:
                continue
            # Snapshots may omit open interest (None = unknown); only a known
            # zero disqualifies a contract.
            if quote.open_interest is not None and quote.open_interest <= 0:
                continue
            if (
                quote.observed_at > evidence.observed_at
                or evidence.observed_at - quote.observed_at > MAX_QUOTE_AGE
            ):
                continue
            if quote.bid is None or quote.ask is None or quote.bid > quote.ask:
                continue
            if quote.ask - quote.bid > self.max_quote_width:
                continue
            grouped.setdefault(quote.expiration, []).append(quote)
        return {expiration: tuple(quotes) for expiration, quotes in grouped.items()}

    def _build_candidate(
        self,
        evidence: MarketEvidence,
        distribution: ForecastDistribution,
        current_price: Decimal,
        expiration: date,
        quotes: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote],
        strategy: Strategy,
    ) -> CandidateStructure | None:
        legs = _legs(quotes, strategy)
        entry_limit = _entry_limit(quotes, strategy)
        if (strategy == Strategy.LONG_VOL and entry_limit <= 0) or (
            strategy == Strategy.SHORT_VOL and entry_limit >= 0
        ):
            return None
        friction = sum(
            (_quote_width(quote) * self.friction_fraction for quote in quotes),
            Decimal("0"),
        )
        fees = self.fee_per_leg * Decimal("4")
        candidate_key = json.dumps(
            {
                "underlying": evidence.underlying,
                "expiration": expiration.isoformat(),
                "strategy": strategy.value,
                "symbols": [quote.symbol for quote in quotes],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        candidate_id = uuid5(
            NAMESPACE_URL,
            hashlib.sha256(candidate_key.encode()).hexdigest(),
        )
        one_lot = CandidateStructure(
            candidate_id=candidate_id,
            strategy=strategy.value,
            underlying=evidence.underlying,
            expiration=expiration,
            legs=legs,
            quantity=1,
            entry_limit=entry_limit,
            max_loss=Decimal("0"),
            modeled_friction=friction,
            modeled_fees=fees,
            robust_ev=Decimal("0"),
        )
        one_lot_max_loss = exact_max_loss(one_lot)
        if one_lot_max_loss <= 0:
            return None
        quantity = min(
            self.portfolio_capacity,
            max(0, int(self.risk_budget // one_lot_max_loss)),
        )
        if quantity <= 0:
            return None
        max_loss = one_lot_max_loss * Decimal(quantity)
        candidate = one_lot.model_copy(update={"quantity": quantity, "max_loss": max_loss})
        robust_ev = min(
            _expected_pnl(candidate, scenario_distribution, current_price)
            for scenario_distribution in self.admissible_distributions(distribution)
        )
        return candidate.model_copy(update={"robust_ev": robust_ev})


def rank_candidates(candidates: Sequence[CandidateStructure]) -> tuple[CandidateStructure, ...]:
    """Rank with a stable key independent of input order."""

    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                -candidate.robust_ev,
                candidate.max_loss,
                abs(candidate.entry_limit),
                ":".join(leg.symbol for leg in candidate.legs),
            ),
        )
    )


def _normalize_strategies(allowed_sides: Iterable[str] | str) -> tuple[Strategy, ...]:
    if isinstance(allowed_sides, str):
        values = BOTH if allowed_sides.upper() == "BOTH" else {allowed_sides.upper()}
    else:
        values = {
            value.value if isinstance(value, Strategy) else str(value).upper()
            for value in allowed_sides
        }
    return tuple(strategy for strategy in Strategy if strategy.value in values)


def _normalize_scenario(scenario: Scenario | str) -> Scenario:
    try:
        return Scenario(scenario)
    except ValueError as exc:
        raise ValueError("candidate scenario is not schema-valid") from exc


def _pairs(quotes: Sequence[OptionQuote]) -> Iterable[tuple[OptionQuote, OptionQuote]]:
    for left_index, left in enumerate(quotes):
        for right in quotes[left_index + 1 :]:
            yield left, right


def _legs(
    quotes: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote], strategy: Strategy
) -> tuple[OptionLeg, OptionLeg, OptionLeg, OptionLeg]:
    put_outer, put_inner, call_inner, call_outer = quotes
    long_vol = strategy == Strategy.LONG_VOL
    return (
        _leg(put_outer, "SELL" if long_vol else "BUY"),
        _leg(put_inner, "BUY" if long_vol else "SELL"),
        _leg(call_inner, "BUY" if long_vol else "SELL"),
        _leg(call_outer, "SELL" if long_vol else "BUY"),
    )


def _leg(quote: OptionQuote, side: str) -> OptionLeg:
    return OptionLeg(
        symbol=quote.symbol,
        underlying=quote.underlying,
        expiration=quote.expiration,
        strike=quote.strike,
        right=quote.right,
        side=cast(OrderSide, side),
        ratio=1,
    )


def _entry_limit(
    quotes: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote], strategy: Strategy
) -> Decimal:
    legs = _legs(quotes, strategy)
    cashflow = Decimal("0")
    for quote, leg in zip(quotes, legs, strict=True):
        assert quote.bid is not None and quote.ask is not None
        cashflow += quote.ask if leg.side == "BUY" else -quote.bid
    return cashflow


def _quote_width(quote: OptionQuote) -> Decimal:
    if quote.bid is None or quote.ask is None:
        raise ValueError("candidate quote is missing a bid or ask")
    return quote.ask - quote.bid


def _expected_pnl(
    candidate: CandidateStructure,
    distribution: ForecastDistribution,
    current_price: Decimal,
) -> Decimal:
    return sum(
        (
            structure_pnl(
                candidate,
                max(Decimal("0"), current_price * (Decimal("1") + node.return_value)),
            )
            * node.probability
            for node in distribution.nodes
        ),
        Decimal("0"),
    )
