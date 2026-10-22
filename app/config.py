from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, PostgresDsn, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr
    # Owners of the business; everyone else is let in from the admin panel.
    admin_ids: Annotated[frozenset[int], NoDecode] = Field(default_factory=frozenset)

    # Public HTTPS address of the Mini App. Without it the bot asks the Cloudflare tunnel.
    webapp_url: str | None = None
    tunnel_metrics_url: str = "http://tunnel:2000"
    # Exposes /docs; keep off when the API is reachable through the tunnel.
    api_docs: bool = False
    # Telegram can't be reached from Russian clouds; there the bot talks to it through
    # the relay in deploy/telegram-relay.
    telegram_api_url: str | None = None
    # Guards the webhook and the job endpoints the cloud timers call. Without it the
    # serverless entry points stay closed and the bot runs by polling.
    hook_secret: SecretStr | None = None

    # A full connection string, such as a hosted Postgres, wins over the parts below.
    database_dsn: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "vending"
    postgres_password: SecretStr = SecretStr("vending")
    postgres_db: str = "vending"

    timezone: str = "Asia/Yekaterinburg"
    log_level: str = "INFO"

    smartvend_api_key: SecretStr | None = None
    smartvend_base_url: str = "https://api.smartvend.ru/v1.2"
    # Where the very first sync starts; later runs resume from the stored cursor.
    smartvend_history_start: date = date(2025, 1, 1)
    # Controllers upload offline sales late, so each run re-reads a few past days.
    sales_lookback_days: int = 3

    default_machine_cost: Decimal = Decimal("320000")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(int(part) for part in value.replace(" ", "").split(",") if part)
        if isinstance(value, int):
            return frozenset({value})
        return value

    @field_validator("webapp_url", "telegram_api_url", "hook_secret", "database_dsn", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return value or None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        if self.database_dsn is not None:
            url = make_url(self.database_dsn.get_secret_value())
            return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password.get_secret_value(),
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @property
    def telegram_reach_url(self) -> str | None:
        """Where Telegram itself can reach us: the relay when there is one, since Telegram
        can't connect to Russian clouds either."""
        return self.telegram_api_url or self.webapp_url

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
