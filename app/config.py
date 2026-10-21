from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, PostgresDsn, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr
    allowed_user_ids: Annotated[frozenset[int], NoDecode] = Field(default_factory=frozenset)

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "vending"
    postgres_password: SecretStr = SecretStr("vending")
    postgres_db: str = "vending"

    timezone: str = "Asia/Yekaterinburg"
    log_level: str = "INFO"

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(int(part) for part in value.replace(" ", "").split(",") if part)
        if isinstance(value, int):
            return frozenset({value})
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
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
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
