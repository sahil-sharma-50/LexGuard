"""Fail-closed runtime settings."""

from decimal import Decimal
from typing import Literal, cast

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated service configuration with a hard paper-account boundary."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        frozen=True,
    )

    environment: Literal["development", "competition"] = "development"
    alpaca_api_key: SecretStr
    alpaca_secret_key: SecretStr
    alpaca_base_url: AnyHttpUrl = Field(
        default=cast(AnyHttpUrl, "https://paper-api.alpaca.markets")
    )
    database_url: str = "postgresql+psycopg://localhost/lexguard"
    openai_api_key: SecretStr | None = None
    openai_model: Literal["gpt-4o-mini"] = "gpt-4o-mini"
    market_timezone: Literal["America/New_York"] = "America/New_York"
    max_trade_loss: Decimal = Decimal("1000")
    max_daily_loss: Decimal = Decimal("1500")
    max_competition_drawdown: Decimal = Decimal("4000")
    entry_enabled: bool = False
    allowed_origin: str = "http://localhost:3000"

    @model_validator(mode="after")
    def paper_only(self) -> "Settings":
        if str(self.alpaca_base_url).rstrip("/") != "https://paper-api.alpaca.markets":
            raise ValueError("ALPACA_BASE_URL must be paper-api")
        if (
            self.max_trade_loss <= 0
            or self.max_daily_loss <= 0
            or self.max_competition_drawdown <= 0
        ):
            raise ValueError("risk limits must be positive")
        return self
