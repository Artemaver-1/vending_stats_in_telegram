from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _kopecks_to_rubles(value: object) -> object:
    if isinstance(value, str | int):
        return Decimal(value) / 100
    return value


def _from_unix(value: object) -> object:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    return value


Rubles = Annotated[Decimal, BeforeValidator(_kopecks_to_rubles)]
UnixTime = Annotated[datetime, BeforeValidator(_from_unix)]
ConnectionStatus = Literal["online", "offline"]


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class Controller(_Model):
    id: str
    name: str = Field(alias="humanName")
    serial_number: str = Field(alias="serialNumber")
    address: str | None = Field(default=None, alias="location")
    connection_status: ConnectionStatus = Field(alias="connectionStatus")

    @property
    def online(self) -> bool:
        return self.connection_status == "online"


class Sale(_Model):
    id: str = Field(alias="saleId")
    controller_id: str = Field(alias="controllerId")
    # Time the sale happened on the device; `createdAt` is when it reached the server.
    sold_at: UnixTime = Field(alias="controllerCreatedAt")
    bill: Rubles
    coin: Rubles
    card: Rubles = Field(alias="digital")
    canceled: bool = False
    hidden: bool = False


class ControllerEvent(_Model):
    id: str
    controller_id: str = Field(alias="controllerId")
    occurred_at: UnixTime = Field(alias="controllerCreatedAt")
    code: str


class Page[ItemT](_Model):
    items: list[ItemT]
    total: int = 0
