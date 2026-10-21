# Vending Ops

Telegram bot and REST API for running a small vending business: two strength-tester
machines in Chelyabinsk. Sales and connectivity are pulled from SmartVend telemetry,
with rent tracking, monthly P&L, payback, uptime history and a lightweight CRM for
new locations.

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
  integrations/  external API clients (SmartVend)
  worker/        scheduled sync jobs and alerts
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

Migrations run automatically in the `migrate` service before the other services start.
API docs are at <http://localhost:8000/docs>.

| Service  | What it does                                                        |
|----------|---------------------------------------------------------------------|
| `bot`    | Telegram bot, long polling                                          |
| `worker` | syncs SmartVend every 5 min (connectivity) and 30 min (sales)       |
| `api`    | FastAPI, bound to localhost                                         |
| `db`     | PostgreSQL 16                                                       |

## Running on a machine that isn't always on

The host is a home computer that is regularly switched off, so nothing relies on it
being up:

- Telegram keeps undelivered updates for 24 hours and the bot processes them on start.
- Each sync stores a cursor in `sync_state`. On boot the worker runs every job immediately
  and continues from the cursor, re-reading a few extra days because controllers upload
  sales recorded while they had no signal.
- Raw sales are upserted by their SmartVend id and daily revenue is rebuilt from them,
  so re-running a sync never double counts.
- Connection alerts older than three hours are stored silently instead of arriving as a
  burst of stale messages after downtime.

## Development

Tests run against PostgreSQL (`TEST_DATABASE_URL`, defaults to a `vending_test` database
on localhost):

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
docker compose up -d db
docker compose exec db createdb -U vending vending_test
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
- Card, coin and bill revenue all come from SmartVend; the Vendista card terminal export is
  only used for reconciliation, so card payments are never counted twice.
- Days are bucketed in `Asia/Yekaterinburg`, where the machines stand, regardless of the
  timezone configured on the controllers.
