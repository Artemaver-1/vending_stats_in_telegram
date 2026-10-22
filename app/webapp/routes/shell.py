from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response

from app import __version__
from app.api.deps import ClockDep, SessionDep
from app.db.models import Attachment
from app.services.rent import RentService
from app.services.staff import UserService
from app.services.tasks import TaskService
from app.webapp.auth import CurrentUser, LinkSigner
from app.webapp.routes import service
from app.webapp.routes.admin import dashboard
from app.webapp.templating import templates

router = APIRouter(prefix="/app")


@router.get("", response_class=HTMLResponse)
async def shell(request: Request) -> HTMLResponse:
    """The page Telegram opens. It has no data of its own: app.js loads the first screen
    with the signed init data, which only exists on the client."""
    return templates.TemplateResponse(request, "shell.html", {"version": __version__})


@router.get("/home", response_class=HTMLResponse)
async def home(
    request: Request, user: CurrentUser, session: SessionDep, clock: ClockDep
) -> HTMLResponse:
    """Each person's start screen, rendered right away: a redirect to it would cost one
    more round trip on every launch."""
    tasks = TaskService(session, clock)
    if user.is_admin:
        return await dashboard.home(
            request, user, session, clock, tasks, RentService(session, clock), UserService(session)
        )
    return await service.home(request, user, tasks, session, clock)


@router.get("/attachments/{attachment_id}")
async def attachment(
    request: Request, attachment_id: int, exp: int, sig: str, session: SessionDep
) -> Response:
    signer: LinkSigner = request.app.state.signer
    if not signer.verify(f"/app/attachments/{attachment_id}", exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ссылка устарела")
    file = await session.get(Attachment, attachment_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return Response(
        file.data,
        media_type=file.content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
