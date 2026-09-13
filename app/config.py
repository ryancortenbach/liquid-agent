from enum import StrEnum
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Mode(StrEnum):
    REAL = "real"
    DEMO = "demo"
    SIM = "sim"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mode: Mode = Mode.DEMO
    demo_clock_speed: float = Field(default=3600, gt=0)
    tick_seconds: float = Field(default=2, gt=0)
    public_base_url: str = "http://localhost:8000"
    tz: str = "America/Los_Angeles"
    database_url: str = "sqlite:///data/liquid.db"

    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5"
    bb_server_url: str = "http://localhost:1234"
    bb_password: str | None = None
    seller_handle: str | None = None
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    shippo_api_key: str | None = None
    google_oauth_client_json: str = "./secrets/gcal_client.json"
    google_token_json: str = "./secrets/gcal_token.json"
    seller_from_address_json: str | None = None

    @field_validator("tz")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
