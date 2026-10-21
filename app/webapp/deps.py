from typing import Annotated

from fastapi import Depends, Request

from app.api.deps import ClockDep, SessionDep
from app.services.notifications import Notifier
from app.services.rent import RentService
from app.services.staff import UserService
from app.services.tasks import TaskService


def get_notifier(request: Request) -> Notifier:
    notifier: Notifier = request.app.state.notifier
    return notifier


def get_tasks(session: SessionDep, clock: ClockDep) -> TaskService:
    return TaskService(session, clock)


def get_rent(session: SessionDep, clock: ClockDep) -> RentService:
    return RentService(session, clock)


def get_users(session: SessionDep) -> UserService:
    return UserService(session)


NotifierDep = Annotated[Notifier, Depends(get_notifier)]
TasksDep = Annotated[TaskService, Depends(get_tasks)]
RentDep = Annotated[RentService, Depends(get_rent)]
UsersDep = Annotated[UserService, Depends(get_users)]
