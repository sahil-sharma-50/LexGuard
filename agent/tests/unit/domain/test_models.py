from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from lexguard.domain.models import (
    CandidateStructure,
    CatalystAssessment,
    ForecastDistribution,
    ForecastNode,
    OptionLeg,
)

EXPIRATION = date(2026, 8, 25)


def node(value: str, probability: str) -> ForecastNode:
    return ForecastNode(return_value=Decimal(value), probability=Decimal(probability))


def leg(
    symbol: str,
    strike: str,
    right: str,
    side: str,
    expiration: date = EXPIRATION,
) -> OptionLeg:
    return OptionLeg(
        symbol=symbol,
        underlying="SPY",
        expiration=expiration,
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
            leg("SPY260825P00575000", "575", "P", "SELL"),
            leg("SPY260825P00580000", "580", "P", "BUY"),
            leg("SPY260825C00590000", "590", "C", "BUY"),
            leg("SPY260825C00595000", "595", "C", "SELL"),
        ),
        quantity=1,
        entry_limit=Decimal("1.00"),
        max_loss=Decimal("500"),
        modeled_friction=Decimal("2"),
        modeled_fees=Decimal("1"),
        robust_ev=Decimal("12.50"),
    )


def test_forecast_probabilities_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        ForecastDistribution(
            nodes=(node("-0.01", "0.4"), node("0.01", "0.5")),
            calibrated_at=datetime(2026, 8, 23, 14, 5, tzinfo=UTC),
            training_end=datetime(2026, 8, 22, 20, tzinfo=UTC),
            artifact_hash="a" * 64,
        )


def test_candidate_requires_exactly_four_same_expiration_legs(
    valid_candidate: CandidateStructure,
) -> None:
    assert len(valid_candidate.legs) == 4
    with pytest.raises(ValidationError):
        valid_candidate.model_copy(update={"legs": valid_candidate.legs[:3]})


def test_candidate_rejects_mixed_expiration_and_non_unit_ratio(
    valid_candidate: CandidateStructure,
) -> None:
    mixed = leg("SPY260826P00575000", "575", "P", "SELL", date(2026, 8, 26))
    with pytest.raises(ValueError, match="same expiration"):
        CandidateStructure.model_validate(
            valid_candidate.model_dump(mode="python") | {"legs": (*valid_candidate.legs[:3], mixed)}
        )

    bad_ratio = valid_candidate.legs[0].model_copy(update={"ratio": 2})
    with pytest.raises(ValueError, match="1:1:1:1"):
        CandidateStructure.model_validate(
            valid_candidate.model_dump(mode="python")
            | {"legs": (bad_ratio, *valid_candidate.legs[1:])}
        )


def test_candidate_rejects_uncovered_side_pattern(
    valid_candidate: CandidateStructure,
) -> None:
    uncovered = valid_candidate.legs[0].model_copy(update={"side": "BUY"})
    with pytest.raises(ValueError, match="covered condor"):
        CandidateStructure.model_validate(
            valid_candidate.model_dump(mode="python")
            | {"legs": (uncovered, *valid_candidate.legs[1:])}
        )


def test_candidate_requires_exact_condor_rights_and_strike_order(
    valid_candidate: CandidateStructure,
) -> None:
    invalid_right = leg("SPY260825C00575000", "575", "C", "SELL")
    with pytest.raises(ValueError, match="covered condor"):
        CandidateStructure.model_validate(
            valid_candidate.model_dump(mode="python")
            | {"legs": (invalid_right, *valid_candidate.legs[1:])}
        )

    with pytest.raises(ValueError, match="covered condor"):
        CandidateStructure.model_validate(
            valid_candidate.model_dump(mode="python")
            | {"legs": (*valid_candidate.legs[1::-1], *valid_candidate.legs[2:])}
        )


def test_candidate_accepts_the_exact_short_vol_condor(
    valid_candidate: CandidateStructure,
) -> None:
    short_legs = tuple(
        item.model_copy(update={"side": "BUY" if item.side == "SELL" else "SELL"})
        for item in valid_candidate.legs
    )
    short = valid_candidate.model_copy(update={"strategy": "SHORT_VOL", "legs": short_legs})

    assert short.strategy == "SHORT_VOL"
    assert tuple(leg.side for leg in short.legs) == ("BUY", "SELL", "SELL", "BUY")


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        CatalystAssessment(
            scenario="BASE",
            confidence=Decimal("0.5"),
            evidence_ids=(),
            rationale="No catalyst.",
            model="gpt-4o-mini",
            prompt_version="v1",
            assessed_at=datetime(2026, 8, 23, 14, 5),
        )


def test_catalyst_rationale_and_confidence_are_bounded() -> None:
    base = {
        "scenario": "BASE",
        "confidence": Decimal("0.5"),
        "evidence_ids": (),
        "rationale": "x" * 800,
        "model": "gpt-4o-mini",
        "prompt_version": "v1",
        "assessed_at": datetime(2026, 8, 23, 14, 5, tzinfo=UTC),
    }
    assert CatalystAssessment(**base).rationale == "x" * 800
    with pytest.raises(ValidationError):
        CatalystAssessment(**(base | {"rationale": "x" * 801}))
    with pytest.raises(ValidationError):
        CatalystAssessment(**(base | {"confidence": Decimal("1.01")}))


def test_collections_are_immutable_tuples(valid_candidate: CandidateStructure) -> None:
    assert isinstance(valid_candidate.legs, tuple)
    distribution = ForecastDistribution(
        nodes=(node("-0.01", "0.4"), node("0.01", "0.6")),
        calibrated_at=datetime(2026, 8, 23, 14, 5, tzinfo=UTC),
        training_end=datetime(2026, 8, 22, 20, tzinfo=UTC),
        artifact_hash="a" * 64,
    )
    assert isinstance(distribution.nodes, tuple)
    with pytest.raises(ValidationError):
        valid_candidate.legs = ()
