import json

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response

from app import __version__
from app.api.deps import SessionDep
from app.db.models import Attachment
from app.webapp.auth import CurrentUser, LinkSigner
from app.webapp.templating import templates

router = APIRouter(prefix="/app")


@router.get("", response_class=HTMLResponse)
async def shell(request: Request) -> HTMLResponse:
    """The page Telegram opens. It has no data of its own: app.js loads the first screen
    with the signed init data, which only exists on the client."""
    return templates.TemplateResponse(request, "shell.html", {"version": __version__})


@router.get("/home")
async def home(user: CurrentUser) -> Response:
    """Sends each person to their own start screen; htmx follows HX-Location in place."""
    path = "/app/admin" if user.is_admin else "/app/service"
    return Response(headers={"HX-Location": json.dumps({"path": path, "target": "#view"})})


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
