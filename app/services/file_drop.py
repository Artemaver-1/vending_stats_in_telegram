import io
import secrets
import zipfile
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from sqlalchemy import delete, select

from app.db import Database
from app.db.models import OutgoingFile

KEEP = timedelta(days=1)
# Telegram downloads documents from a link only when they are ZIP or PDF.
LINKABLE = (".zip", ".pdf")


def zipped(filename: str, data: bytes) -> tuple[str, bytes]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, data)
    return filename + ".zip", buffer.getvalue()


class FileDrop:
    """Puts a file at an unguessable public address for Telegram to pick up."""

    def __init__(self, db: Database, base_url: str) -> None:
        self.db = db
        self.base_url = base_url.rstrip("/")

    async def put(self, filename: str, data: bytes) -> str:
        file_id = secrets.token_hex(16)
        async with self.db.session() as session:
            session.add(
                OutgoingFile(id=file_id, filename=filename, data=data, created_at=datetime.now(UTC))
            )
        return f"{self.base_url}/files/{file_id}/{quote(filename)}"

    async def get(self, file_id: str) -> OutgoingFile | None:
        async with self.db.session() as session:
            item = await session.scalar(select(OutgoingFile).where(OutgoingFile.id == file_id))
        if item is None or datetime.now(UTC) - item.created_at > KEEP:
            return None
        return item

    async def purge(self) -> None:
        async with self.db.session() as session:
            await session.execute(
                delete(OutgoingFile).where(OutgoingFile.created_at < datetime.now(UTC) - KEEP)
            )
