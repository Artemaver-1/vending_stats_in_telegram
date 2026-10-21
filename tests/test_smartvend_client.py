import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.integrations.smartvend import SmartVendClient, SmartVendError


def success(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"id": "x", "result": {"$case": "success", "success": payload}})


def sale(n: int) -> dict[str, object]:
    return {
        "saleId": f"sale-{n}",
        "controllerId": "ctrl",
        "controllerCreatedAt": 1792312500 + n,
        "createdAt": 1792449637,
        "bill": "1000",
        "coin": "0",
        "digital": "0",
        "canceled": False,
        "hidden": False,
    }


async def test_sales_are_paginated_and_converted_to_rubles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.smartvend.client.PAGE_SIZE", 2)
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        assert request.headers["Authorization"] == "Bearer smvd_test"
        page = body["pagination"]["currentPage"]
        items = [sale(1), sale(2)] if page == 1 else [sale(3)]
        return success({"items": items, "total": 3})

    async with SmartVendClient("smvd_test", transport=httpx.MockTransport(handler)) as client:
        start, end = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)
        sales = [s async for s in client.sales(start, end)]

    assert [s.id for s in sales] == ["sale-1", "sale-2", "sale-3"]
    assert sales[0].bill == Decimal("10")
    assert sales[0].sold_at == datetime.fromtimestamp(1792312501, tz=UTC)
    assert len(requests) == 2
    assert requests[0]["dateRange"] == {"from": int(start.timestamp()), "to": int(end.timestamp())}


async def test_failure_envelope_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"result": {"$case": "failure", "failure": {"code": "400", "message": "bad"}}},
        )

    async with SmartVendClient("k", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SmartVendError, match="bad"):
            await client.controllers()


async def test_server_errors_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.integrations.smartvend.client.asyncio.sleep", no_sleep)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(502, text="Bad Gateway")
        return success(
            {
                "items": [
                    {
                        "id": "c1",
                        "humanName": "Пушкина",
                        "serialNumber": "25100241",
                        "location": None,
                        "place": None,
                        "connectionStatus": "online",
                    }
                ]
            }
        )

    async with SmartVendClient("k", transport=httpx.MockTransport(handler)) as client:
        controllers = await client.controllers()

    assert calls == 3
    assert controllers[0].online


async def test_unreachable_server_explains_itself() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("handshake timed out", request=request)

    async with SmartVendClient("k", retries=1, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SmartVendError) as raised:
            await client.controllers()
    assert "VPN" in raised.value.reason
