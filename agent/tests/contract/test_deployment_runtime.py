"""Deployment contract checks for the runtime's migration and health boundary."""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_agent_image_contains_alembic_assets_and_runs_migrations_as_release_step() -> None:
    dockerfile = (ROOT.parent / "infra" / "Dockerfile.agent").read_text(encoding="utf-8")
    railway = (ROOT.parent / "infra" / "railway.toml").read_text(encoding="utf-8")
    scheduler_railway = (ROOT.parent / "infra" / "railway.scheduler.toml").read_text(
        encoding="utf-8"
    )

    assert "COPY agent/alembic.ini" in dockerfile
    assert "COPY agent/migrations" in dockerfile
    assert "preDeployCommand" in railway
    assert "alembic upgrade head" in railway
    assert 'startCommand = "lexguard serve --host 0.0.0.0 --port 8000"' in railway
    # The worker boots by seeding runtime artifacts, then execs the watch loop.
    assert "lexguard seed-risk-state" in scheduler_railway
    assert "lexguard seed-forecast --symbol SPY" in scheduler_railway
    assert "exec lexguard scheduler --watch" in scheduler_railway
    assert "alembic upgrade head" in scheduler_railway
