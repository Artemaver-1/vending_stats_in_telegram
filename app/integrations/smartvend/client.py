import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Self

import httpx
from pydantic import BaseModel

from app.integrations.smartvend.schemas import Controller, ControllerEvent, Page, Sale

logger = logging.getLogger(__name__)

PAGE_SIZE = 1000


UNREACHABLE = (
    "Сервер SmartVend не отвечает. Если на компьютере с ботом включён VPN, "
    "добавьте smartvend.ru в исключения VPN или выключите его."
)


class SmartVendError(Exception):
    """`reason` is a sentence for people; the exception text keeps technical details."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def _transport_reason(exc: httpx.TransportError) -> str:
    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout):
        return UNREACHABLE
    if isinstance(exc, httpx.TimeoutException):
        return "SmartVend отвечает слишком долго, попробуйте позже."
    return "Не удалось связаться с SmartVend."


class SmartVendClient:
    """Thin async wrapper over the SmartVend v1.2 API.

    Every endpoint is a POST that answers `{"result": {"$case": "success" | "failure", ...}}`,
    even for errors, so the envelope is unpacked here and failures become exceptions.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.smartvend.ru/v1.2",
        *,
        timeout: float = 30.0,
        connect_timeout: float = 10.0,
        retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            transport=transport,
        )
        self._retries = retries

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    async def controllers(self) -> list[Controller]:
        data = await self._call("get-list-of-controllers", {"filters": {}})
        return Page[Controller].model_validate(data).items

    async def sales(self, start: datetime, end: datetime) -> AsyncIterator[Sale]:
        # A stable order keeps pages from shifting while new sales arrive mid-pagination.
        sort = {"field": "controllerCreatedAt", "direction": "asc"}
        async for item in self._paginate("get-list-of-sales", start, end, Sale, sort=sort):
            yield item

    async def events(self, start: datetime, end: datetime) -> AsyncIterator[ControllerEvent]:
        async for item in self._paginate("get-list-of-events", start, end, ControllerEvent):
            yield item

    async def _paginate[ItemT: BaseModel](
        self,
        endpoint: str,
        start: datetime,
        end: datetime,
        item_type: type[ItemT],
        *,
        sort: dict[str, str] | None = None,
    ) -> AsyncIterator[ItemT]:
        page_number = 1
        seen = 0
        while True:
            payload: dict[str, Any] = {
                "pagination": {"currentPage": page_number, "perPage": PAGE_SIZE},
                "dateRange": {"from": int(start.timestamp()), "to": int(end.timestamp())},
                "filters": {},
            }
            if sort is not None:
                payload["sort"] = sort
            page = Page[item_type].model_validate(await self._call(endpoint, payload))  # type: ignore[valid-type]
            for item in page.items:
                yield item
            seen += len(page.items)
            if not page.items or seen >= page.total:
                return
            page_number += 1

    async def _call(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(1, self._retries + 1):
            try:
                response = await self._http.post(endpoint, json=payload)
            except httpx.TransportError as exc:
                if attempt == self._retries:
                    raise SmartVendError(
                        f"{endpoint}: {type(exc).__name__} {exc}", _transport_reason(exc)
                    ) from exc
            else:
                if response.status_code < 500 or attempt == self._retries:
                    return self._unwrap(endpoint, response)
            delay = 2**attempt
            logger.warning(
                "SmartVend %s failed (attempt %d), retrying in %ds", endpoint, attempt, delay
            )
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _unwrap(endpoint: str, response: httpx.Response) -> dict[str, Any]:
        try:
            result = response.json()["result"]
        except (ValueError, KeyError) as exc:
            raise SmartVendError(
                f"{endpoint}: unexpected response {response.status_code}",
                f"SmartVend временно недоступен (ошибка {response.status_code}).",
            ) from exc
        if result.get("$case") != "success":
            failure = result.get("failure", {})
            raise SmartVendError(
                f"{endpoint}: {failure.get('code')} {failure.get('message')}",
                f"SmartVend вернул ошибку: {failure.get('message') or failure.get('code')}.",
            )
        success: dict[str, Any] = result["success"]
        return success
