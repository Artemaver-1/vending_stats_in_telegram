import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("111, 222,333", {111, 222, 333}),
        ("111", {111}),
        ("", set()),
    ],
)
def test_allowed_ids_from_env(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: set[int]
) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_IDS", raw)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.allowed_user_ids == expected


def test_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.database_url.startswith("postgresql+asyncpg://vending:")
    assert settings.database_url.endswith("@db:5432/vending")
