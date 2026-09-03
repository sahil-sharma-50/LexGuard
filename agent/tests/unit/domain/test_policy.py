from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from lexguard.domain.models import CandidateStructure, OptionLeg
from lexguard.domain.policy import RiskContext, RiskPolicy

UTC = UTC
EXPIRATION = date(2026, 8, 25)
NOW = datetime(2026, 8, 24, 14, 10, tzinfo=UTC)


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


@pytest.fixture
def valid_candidate() -> CandidateStructure:
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


@pytest.fixture
def safe_context() -> RiskContext:
    return RiskContext(
        now=NOW,
        decision_window="10:05",
        evidence_observed_at=NOW,
        daily_pnl=Decimal("0"),
        competition_drawdown=Decimal("0"),
        entries_today=0,
        traded_symbols_today=(),
        open_structure_count=0,
        open_order_count=0,
        open_position_count=0,
        account_status="ACTIVE",
        options_level=3,
        opra_available=True,
        base_url="https://paper-api.alpaca.markets",
        certificate_expires_at=NOW + timedelta(minutes=5),
    )


def test_policy_rejects_trade_loss_over_1000(
    valid_candidate: CandidateStructure,
    safe_context: RiskContext,
) -> None:
    candidate = valid_candidate.model_copy(update={"max_loss": Decimal("1000.01")})
    result = RiskPolicy().evaluate(candidate, safe_context)
    assert "MAX_TRADE_LOSS" in result.reason_codes


def test_policy_rejects_second_position(
    valid_candidate: CandidateStructure,
    safe_context: RiskContext,
) -> None:
    result = RiskPolicy().evaluate(
        valid_candidate,
        safe_context.model_copy(update={"open_structure_count": 1}),
    )
    assert "OPEN_STRUCTURE_EXISTS" in result.reason_codes


def test_policy_returns_all_refusals_in_stable_order(
    valid_candidate: CandidateStructure,
    safe_context: RiskContext,
) -> None:
    context = safe_context.model_copy(
        update={
            "daily_pnl": Decimal("-1500"),
            "competition_drawdown": Decimal("4000"),
            "entries_today": 2,
            "traded_symbols_today": ("SPY",),
            "opra_available": False,
            "base_url": "https://api.alpaca.markets",
        }
    )
    result = RiskPolicy().evaluate(valid_candidate, context)
    assert result.allowed is False
    assert result.reason_codes == tuple(sorted(result.reason_codes))
    assert {"DAILY_LOSS_LIMIT", "COMPETITION_DRAWDOWN", "DAILY_ENTRY_LIMIT"}.issubset(
        result.reason_codes
    )


def test_policy_rejects_stale_evidence_and_out_of_window(
    valid_candidate: CandidateStructure,
    safe_context: RiskContext,
) -> None:
    context = safe_context.model_copy(
        update={
            "now": NOW.replace(hour=14, minute=9),
            "evidence_observed_at": NOW - timedelta(minutes=10),
            "entry_attempt": True,
        }
    )
    result = RiskPolicy().evaluate(valid_candidate, context)
    assert "ENTRY_WINDOW_CLOSED" in result.reason_codes
    assert "STALE_EVIDENCE" in result.reason_codes
