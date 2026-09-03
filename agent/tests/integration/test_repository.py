import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest

from lexguard.adapters.repository import (
    Base,
    CaseRepository,
    DuplicateDecisionWindow,
)
from lexguard.domain.state_machine import CaseEventType


@pytest.fixture
def repository() -> CaseRepository:
    database_url = os.environ.get("LEXGUARD_TEST_DATABASE_URL", "sqlite://")
    repository = CaseRepository(database_url)
    Base.metadata.drop_all(repository.engine)
    repository.create_schema()
    return repository


def test_duplicate_window_is_impossible(repository: CaseRepository) -> None:
    repository.create_scheduled(date(2026, 8, 24), "10:05")
    with pytest.raises(DuplicateDecisionWindow):
        repository.create_scheduled(date(2026, 8, 24), "10:05")


def test_lease_allows_one_owner(repository: CaseRepository) -> None:
    trading_date = date(2026, 8, 24)
    assert repository.acquire_window_lease(trading_date, "10:05", "worker-a") is True
    assert repository.acquire_window_lease(trading_date, "10:05", "worker-b") is False


def test_expired_lease_can_be_reclaimed(repository: CaseRepository) -> None:
    trading_date = date(2026, 8, 24)
    assert (
        repository.acquire_window_lease(
            trading_date,
            "13:05",
            "worker-a",
            now=repository.clock() - timedelta(minutes=5),
            ttl=timedelta(minutes=1),
        )
        is True
    )
    assert repository.acquire_window_lease(trading_date, "13:05", "worker-b") is True


def test_daily_entry_state_uses_durable_submitted_cases(repository: CaseRepository) -> None:
    trading_date = date(2026, 8, 24)
    submitted = repository.create_scheduled(trading_date, "10:05", underlying="SPY")
    for event in (
        CaseEventType.OBSERVED,
        CaseEventType.FORECASTED,
        CaseEventType.ARGUED,
        CaseEventType.CERTIFIED,
        CaseEventType.SUBMITTED,
    ):
        submitted = repository.append_event(submitted.case_id, event)
    repository.create_scheduled(trading_date, "13:05", underlying="QQQ")

    state = repository.daily_entry_state(trading_date)

    assert state.entries_today == 1
    assert state.traded_symbols_today == ("SPY",)


@pytest.mark.skipif(
    "LEXGUARD_TEST_DATABASE_URL" not in os.environ,
    reason="concurrency gate requires PostgreSQL",
)
def test_concurrent_lease_attempts_have_one_winner() -> None:
    database_url = os.environ["LEXGUARD_TEST_DATABASE_URL"]
    repositories = [CaseRepository(database_url), CaseRepository(database_url)]
    Base.metadata.drop_all(repositories[0].engine)
    repositories[0].create_schema()

    def acquire(index: int) -> bool:
        return repositories[index].acquire_window_lease(
            date(2026, 8, 26), "10:05", f"worker-{index}"
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(acquire, (0, 1)))
    assert sorted(results) == [False, True]
