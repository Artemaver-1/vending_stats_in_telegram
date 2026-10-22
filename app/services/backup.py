import asyncio
import gzip
import os

from sqlalchemy.engine import make_url


class BackupError(Exception):
    pass


class DatabaseBackup:
    """A plain pg_dump of the whole database, gzipped; scripts/restore.sh loads it back."""

    def __init__(self, database_url: str) -> None:
        self.url = make_url(database_url)

    async def dump(self) -> bytes:
        env = {
            **os.environ,
            "PGHOST": self.url.host or "localhost",
            "PGPORT": str(self.url.port or 5432),
            "PGUSER": self.url.username or "",
            "PGPASSWORD": self.url.password or "",
            "PGDATABASE": self.url.database or "",
        }
        process = await asyncio.create_subprocess_exec(
            "pg_dump",
            "--clean",
            "--if-exists",
            # A hosted Postgres keeps its own schemas next to ours; those aren't ours to copy.
            "--schema=public",
            # Files waiting for Telegram to pick them up are gone within a day anyway.
            "--exclude-table-data=outgoing_files",
            "--no-owner",
            "--no-privileges",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await process.communicate()
        if process.returncode != 0:
            raise BackupError(err.decode(errors="replace").strip() or "pg_dump failed")
        return gzip.compress(out)
