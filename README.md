# Vending Ops

Telegram Mini App for running a small vending business: two strength-tester machines in
Chelyabinsk. Sales and connectivity are pulled from SmartVend telemetry; the owner gets an
admin panel with P&L, payback, rent schedule and uptime, the service crew gets a dead-simple
task list with weekly inspection checklists.

## Roles

- **Admin** — dashboard, tasks for the crew (with a QR code or file attached), purchase
  requests coming from inspections, economics per month and per machine, rent contracts
  with accruals and payment marks, machine status and uptime, team access.
- **Service** — "Обслуживание силомеров": open tasks, a four-question inspection with big
  yes/no buttons and a "what to order" field. If the machine as a whole doesn't work it is
  marked broken, the admin is alerted and weekly inspections pause until a repair check
  passes. Reminders arrive two days and one day before a task is due.

Everyone who opens the bot is recorded as an access request; admins (from `ADMIN_IDS`)
let people in from the Team screen.

## Stack

- Python 3.12, aiogram 3, FastAPI
- Mini App: server-rendered Jinja2 + htmx, Telegram theme colours, SVG charts drawn in Python
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
  bot/           aiogram: access requests, menu button, notifications
  webapp/        Mini App: init-data auth, templates, admin and service screens
  api/           FastAPI app factory and JSON routes
migrations/      Alembic revisions
tests/
```

## Running

```bash
cp .env.example .env   # fill in BOT_TOKEN, ADMIN_IDS and SMARTVEND_API_KEY
docker compose up -d --build
```

Migrations run automatically in the `migrate` service before the other services start.
API docs are at <http://localhost:8000/docs>.

| Service  | What it does                                                        |
|----------|---------------------------------------------------------------------|
| `bot`    | Telegram bot, long polling                                          |
| `worker` | syncs SmartVend every 5 min (connectivity) and 30 min (sales)       |
| `api`    | FastAPI: Mini App and JSON API                                      |
| `tunnel` | Cloudflare quick tunnel giving the Mini App a public HTTPS address  |
| `db`     | PostgreSQL 16                                                       |

Telegram only opens Mini Apps over HTTPS. The quick tunnel needs no account or domain but
gets a new address on every restart; the bot reads it from the tunnel's metrics endpoint
and re-points everyone's menu button. Set `WEBAPP_URL` to use a fixed address instead.

Every screen checks the Telegram-signed init data sent by `app.js`; images such as QR codes
use short-lived signed links because the browser loads them without headers.

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
