"""The public status probe must not claim a missing ledger is healthy."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from lexguard.adapters.repository import Base, CaseRepository
from lexguard.api.app import create_app


def test_repository_api_returns_unhealthy_when_migrations_are_missing() -> None:
    repository = CaseRepository("sqlite://")
    response = TestClient(create_app(repository=repository)).get("/api/status")

    assert response.status_code == 503
    assert response.json()["components"]["database"] == "migration_required"


def test_repository_api_status_is_healthy_after_schema_is_present() -> None:
    repository = CaseRepository("sqlite://")
    Base.metadata.create_all(repository.engine)
    with repository.engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
        text("INSERT INTO alembic_version(version_num) VALUES ('0003_system_decision_window')")
        )
    response = TestClient(create_app(repository=repository)).get("/api/status")

    assert response.status_code == 200
    assert response.json()["components"]["database"] == "healthy"
