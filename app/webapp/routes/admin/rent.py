from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.api.deps import SessionDep
from app.db.models import RentContract
from app.domain.enums import RentType
from app.domain.finance import ZERO
from app.domain.periods import iter_months, month_start
from app.formatting import MONTHS_SHORT
from app.repositories import LocationRepository
from app.services.rent import ContractTerms, RentError
from app.webapp.auth import AdminUser
from app.webapp.charts import BarChart, Series
from app.webapp.deps import RentDep
from app.webapp.routes.admin.common import admin_page

router = APIRouter(prefix="/app/admin/rent")

CHART_MONTHS = 12


@router.get("", response_class=HTMLResponse)
async def rent_page(
    request: Request, _: AdminUser, session: SessionDep, rent: RentDep, toast: str | None = None
) -> HTMLResponse:
    await rent.sync_accruals()
    payments = await rent.payments()
    unpaid_first = sorted(payments, key=lambda p: (p.is_paid, -p.period.toordinal()))

    chart = None
    if payments:
        by_month: dict[date, Decimal] = defaultdict(lambda: ZERO)
        for payment in payments:
            by_month[payment.period] += payment.amount
        last = max(by_month)
        months = list(iter_months(date(last.year - 1, last.month, 1), last))[-CHART_MONTHS:]
        chart = BarChart(
            [MONTHS_SHORT[m.month - 1] for m in months],
            [Series("аренда", [by_month.get(m, ZERO) for m in months], "bar-rent")],
        ).render()

    return await admin_page(
        request,
        session,
        "admin/rent.html",
        tab="rent",
        payments=unpaid_first,
        upcoming=await rent.upcoming(),
        contracts=await rent.contracts(),
        chart=chart,
        toast=toast,
    )


@router.post("/payments/{payment_id}/{action}", response_class=HTMLResponse)
async def toggle_payment(
    request: Request,
    payment_id: int,
    action: str,
    admin: AdminUser,
    session: SessionDep,
    rent: RentDep,
) -> HTMLResponse:
    payment = await rent.get_payment(payment_id)
    if payment is None or action not in {"paid", "unpaid"}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Платёж не найден")
    await rent.set_paid(payment, action == "paid")
    toast = "Отмечено как оплачено" if action == "paid" else "Отметка снята"
    return await rent_page(request, admin, session, rent, toast=toast)


# Decorators apply bottom-up: "/new" has to be registered before the "{contract_id}" pattern.
@router.get("/contracts/{contract_id}", response_class=HTMLResponse)
@router.get("/contracts/new", response_class=HTMLResponse)
async def contract_form(
    request: Request,
    _: AdminUser,
    session: SessionDep,
    rent: RentDep,
    contract_id: int | None = None,
) -> HTMLResponse:
    contract = await _contract(rent, contract_id) if contract_id is not None else None
    return await admin_page(
        request,
        session,
        "admin/contract_form.html",
        tab="rent",
        back="/app/admin/rent",
        contract=contract,
        locations=await LocationRepository(session).list_active(),
    )


@router.post("/contracts", response_class=HTMLResponse)
@router.post("/contracts/{contract_id}", response_class=HTMLResponse)
async def save_contract(
    request: Request,
    admin: AdminUser,
    session: SessionDep,
    rent: RentDep,
    location_id: Annotated[int, Form()],
    rent_type: Annotated[RentType, Form()],
    amount: Annotated[str, Form()],
    payment_day: Annotated[int, Form()],
    valid_from: Annotated[date, Form()],
    valid_to: Annotated[str, Form()] = "",
    contract_id: int | None = None,
) -> HTMLResponse:
    contract = await _contract(rent, contract_id) if contract_id is not None else None
    try:
        terms = ContractTerms(
            location_id=location_id,
            rent_type=rent_type,
            amount=Decimal(amount.replace(",", ".")),
            payment_day=payment_day,
            valid_from=month_start(valid_from),
            valid_to=date.fromisoformat(valid_to) if valid_to else None,
        )
        await rent.save_contract(terms, contract)
    except (RentError, InvalidOperation, ValueError) as exc:
        message = str(exc) if isinstance(exc, RentError) else "Проверьте сумму и даты"
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message) from exc
    return await rent_page(request, admin, session, rent, toast="Договор сохранён")


@router.delete("/contracts/{contract_id}", response_class=HTMLResponse)
async def delete_contract(
    request: Request, contract_id: int, admin: AdminUser, session: SessionDep, rent: RentDep
) -> HTMLResponse:
    await rent.delete_contract(await _contract(rent, contract_id))
    return await rent_page(request, admin, session, rent, toast="Договор удалён")


async def _contract(rent: RentDep, contract_id: int) -> RentContract:
    contract = await rent.get_contract(contract_id)
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Договор не найден")
    return contract
