FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .

COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd --create-home --uid 1000 app
USER app

CMD ["python", "-m", "app.bot"]
