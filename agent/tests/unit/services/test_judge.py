"""Pure deterministic judge tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from lexguard.adapters.repository import CaseRead
from lexguard.domain.hashing import canonical_sha256
from lexguard.domain.models import (
    CandidateStructure,
    CatalystAssessment,
    OptionLeg,
)
from lexguard.domain.policy import RiskContext
from lexguard.domain.state_machine import CaseState
from lexguard.services.judge import Judge

NOW = datetime(2026, 8, 24, 14, 10, tzinfo=UTC)
EXPIRATION = date(2026, 8, 25)
CASE_ID = UUID("44444444-4444-4444-4444-444444444444")


def _leg(symbol: str, strike: str, right: str, side: str) -> OptionLeg:
    return OptionLeg(
        symbol=symbol,
        underlying="SPY",
        expiration=EXPIRATION,
        strike=Decimal(strike),
        right=right,
        side=side,
        ratio=1,
    )


def _candidate(*, robust_ev: str = "20", max_loss: str = "500") -> CandidateStructure:
    return CandidateStructure(
        candidate_id=uuid4(),
        strategy="LONG_VOL",
        underlying="SPY",
        expiration=EXPIRATION,
        legs=(
            _leg("SPY260825P00575000", "575", "P", "SELL"),
            _leg("SPY260825P00580000", "580", "P", "BUY"),
            _leg("SPY260825C00590000", "590", "C", "BUY"),
            _leg("SPY260825C00595000", "595", "C", "SELL"),
        ),
        quantity=1,
        entry_limit=Decimal("1"),
        max_loss=Decimal(max_loss),
        modeled_friction=Decimal("2"),
        modeled_fees=Decimal("1"),
        robust_ev=Decimal(robust_ev),
    )


def _context(**updates: object) -> RiskContext:
    values: dict[str, object] = {
        "now": NOW,
        "decision_window": "10:05",
        "evidence_observed_at": NOW,
        "daily_pnl": Decimal("0"),
        "competition_drawdown": Decimal("0"),
        "account_equity": Decimal("100000"),
        "entries_today": 0,
        "traded_symbols_today": (),
        "open_structure_count": 0,
        "open_order_count": 0,
        "open_position_count": 0,
        "account_status": "ACTIVE",
        "options_level": 3,
        "opra_available": True,
        "base_url": "https://paper-api.alpaca.markets",
    }
    values.update(updates)
    return RiskContext(**values)


def _case() -> CaseRead:
    return CaseRead(CASE_ID, date(2026, 8, 24), "10:05", CaseState.ARGUED, "SPY")


def test_certificate_hash_binds_recomputed_candidate() -> None:
    candidate = _candidate(max_loss="1")
    result = Judge().certify(_case(), (candidate,), _context())

    assert result.candidate.max_loss == Decimal("103")  # type: ignore[union-attr]
    assert result.proposal_hash == canonical_sha256(result.candidate)  # type: ignore[union-attr]
    assert result.expires_at == NOW + timedelta(minutes=10)  # type: ignore[union-attr]


def test_veto_is_a_first_class_refusal() -> None:
    assessment = CatalystAssessment(
        scenario="VETO",
        confidence=Decimal("0"),
        evidence_ids=(),
        rationale="No defensible catalyst.",
        model="gpt-4o-mini",
        prompt_version="catalyst.v1",
        assessed_at=NOW,
    )
    result = Judge().certify(_case(), (_candidate(),), _context(), catalyst=assessment)

    assert result.reason_codes == ("CATALYST_VETO",)  # type: ignore[union-attr]


def test_all_policy_refusals_are_stably_sorted() -> None:
    result = Judge().certify(
        _case(),
        (_candidate(robust_ev="-1"),),
        _context(
            daily_pnl=Decimal("-1500"),
            competition_drawdown=Decimal("4000"),
            entries_today=2,
            opra_available=False,
        ),
    )

    assert result.reason_codes == tuple(sorted(result.reason_codes))  # type: ignore[union-attr]
    assert "ROBUST_EV_NON_POSITIVE" in result.reason_codes  # type: ignore[union-attr]


def test_empty_candidates_refuse_without_certificate() -> None:
    result = Judge().certify(_case(), (), _context())

    assert result.reason_codes == ("NO_ELIGIBLE_CANDIDATE",)  # type: ignore[union-attr]
