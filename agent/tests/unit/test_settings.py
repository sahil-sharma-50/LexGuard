from decimal import Decimal

import pytest

from lexguard.settings import Settings


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")


def test_non_paper_endpoint_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")

    with pytest.raises(ValueError, match="paper-api"):
        Settings()


def test_risk_limits_are_frozen(valid_env: None) -> None:
    settings = Settings()

    assert settings.max_trade_loss == Decimal("1000")
    assert settings.max_daily_loss == Decimal("1500")
    assert settings.max_competition_drawdown == Decimal("4000")


def test_catalyst_model_is_gpt4o_mini_only(valid_env: None) -> None:
    settings = Settings()

    assert settings.openai_model == "gpt-4o-mini"

    with pytest.raises(ValueError):
        Settings(openai_model="gpt-5.6-terra")
