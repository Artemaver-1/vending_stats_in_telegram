# Vending Ops

Telegram bot and REST API for running a small vending business: two strength-tester
machines in Chelyabinsk, with revenue pulled from telemetry and card terminals, rent
tracking, monthly P&L, payback and a lightweight CRM for new locations.

## Stack

- Python 3.12, aiogram 3, FastAPI
- PostgreSQL 16, SQLAlchemy 2 (async), Alembic
- Docker Compose

## Layout

```
app/
  domain/        pure business rules: enums, P&L and payback math, month helpers
  db/            SQLAlchemy models and session management
  repositories/  queries, one class per aggregate
  services/      use cases shared by the bot and the API
  bot/           aiogram handlers, keyboards, middlewares
  api/           FastAPI routes
migrations/      Alembic revisions
tests/
```

## Running

```bash
cp .env.example .env   # fill in BOT_TOKEN and ALLOWED_USER_IDS
docker compose up -d --build
```

Migrations run automatically in the `migrate` service before the bot and API start.
API docs are at <http://localhost:8000/docs>.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/mypy app
```

## How profit is calculated

- Rent comes from contract terms (fixed amount or a percentage of the location's revenue),
  so a month's profit is correct before the rent for it is actually paid.
- In a per-machine report the location rent is split evenly between machines at that
  location, and shared expenses that aren't tied to a machine are excluded.
- Payback is the first month in which cumulative net profit since launch covers the
  purchase cost of the machine.
