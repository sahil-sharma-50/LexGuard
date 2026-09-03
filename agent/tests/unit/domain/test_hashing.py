from datetime import date
from decimal import Decimal
from uuid import uuid4

from lexguard.domain.hashing import canonical_sha256
from lexguard.domain.models import CandidateStructure, OptionLeg


def candidate() -> CandidateStructure:
    expiration = date(2026, 8, 25)
    legs = tuple(
        OptionLeg(
            symbol=symbol,
            underlying="SPY",
            expiration=expiration,
            strike=strike,
            right=right,
            side=side,
            ratio=1,
        )
        for symbol, strike, right, side in (
            ("SPY260825P00575000", Decimal("575"), "P", "SELL"),
            ("SPY260825P00580000", Decimal("580"), "P", "BUY"),
            ("SPY260825C00590000", Decimal("590"), "C", "BUY"),
            ("SPY260825C00595000", Decimal("595"), "C", "SELL"),
        )
    )
    return CandidateStructure(
        candidate_id=uuid4(),
        strategy="LONG_VOL",
        underlying="SPY",
        expiration=expiration,
        legs=legs,
        quantity=1,
        entry_limit=Decimal("1.00"),
        max_loss=Decimal("500"),
        modeled_friction=Decimal("2"),
        modeled_fees=Decimal("1"),
        robust_ev=Decimal("12.50"),
    )


def test_hash_is_independent_of_dictionary_order() -> None:
    valid_candidate = candidate()
    left = canonical_sha256(valid_candidate)
    right = canonical_sha256(CandidateStructure.model_validate(valid_candidate.model_dump()))
    assert left == right


def test_hash_is_sha256_hex_and_decimal_json_is_string() -> None:
    value = candidate()
    assert len(canonical_sha256(value)) == 64
    assert isinstance(value.model_dump(mode="json")["entry_limit"], str)
