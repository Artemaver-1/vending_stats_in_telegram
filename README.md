# Vending Ops

Telegram Mini App for running a small vending business: two strength-tester machines in
Chelyabinsk. Sales and connectivity are pulled from SmartVend telemetry; the owner gets an
admin panel with P&L, payback, rent schedule and uptime, the service crew gets a dead-simple
task list with weekly inspection checklists.

## Roles

- **Admin** — dashboard with a button to pull fresh SmartVend data, tasks for the crew
  (with a QR code or file attached), "Инфа от работника" — every report the crew files,
  an income statement (ОФР) for any period and any machine, economics per month,
  rent contracts with accruals and payment marks,
  machine status and uptime, team access.
- **Service** — "Обслуживание силомеров": one-off tasks from the admin and the list of
  machines. On site the worker opens a machine, sees its state after the previous visit
  and answers four yes/no questions (machine usable at all, coin acceptor, bill acceptor,
  Vendista terminal) plus a free comment. Each report is sent to the admin at once.
  A report counts as the weekly inspection; the next one is due a week later, with
  reminders two days and one day before. If the machine isn't usable at all it is marked
  broken and weekly inspections pause until a report says it works again.

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

## Backups and moving to another computer

Postgres keeps its data in the `pgdata` Docker volume, so it survives container rebuilds
but lives on this machine only. The `backup` service writes a compressed `pg_dump` to
`./backups` on start and every 24 hours, keeping 30 days (`BACKUP_KEEP_DAYS`).

```bash
scripts/backup-now.sh                          # fresh dump into ./backups
scripts/restore.sh backups/vending-....sql.gz   # load a dump into the running db
```

To move: take a fresh dump and stop everything on the old machine (two bots polling the
same token conflict), then on the new one clone the repo, copy `.env` and the dump,
`docker compose up -d db`, run `scripts/restore.sh <dump>` and `docker compose up -d`.

## Historical card revenue

Before SmartVend was installed, card payments are known only from the Vendista terminal.
Admin → Аппараты → Вендиста accepts the "Транзакции" CSV export: successful payments
minus successful refunds, Moscow time converted to Chelyabinsk, and only for days before
the machine's first SmartVend sale, so nothing is counted twice.

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

The bot chat has no commands or menus: `/start` shows a welcome card with a button that
opens the Mini App, and the chat otherwise only carries notifications.

## How profit is calculated

The income statement runs top to bottom: revenue by payment channel with its share,
cost of sales (rent, parts, repair, SIM cards, SmartVend fee, staff, other), taxes,
insurance contributions, net profit.

- Rent comes from contract terms (fixed amount or a percentage of the location's revenue),
  so a period's profit is correct before the rent for it is actually paid. A fixed rent is
  prorated by days when a period covers part of a month; a percentage rent applies to the
  revenue of exactly those days. Rent entered by hand as an expense is added on top.
- In a per-machine report the location rent is split evenly between machines at that
  location, and expenses that aren't tied to a machine are split between active machines.
- Payback is the first month in which cumulative net profit since launch covers the
  purchase cost of the machine.
- Card, coin and bill revenue all come from SmartVend; the Vendista card terminal export is
  only used for reconciliation, so card payments are never counted twice.
- Days are bucketed in `Asia/Yekaterinburg`, where the machines stand, regardless of the
  timezone configured on the controllers.
