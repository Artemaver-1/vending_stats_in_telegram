# pg_dump for the nightly backup has to be at least as new as the server (17 on Supabase),
# newer than the one Debian ships. Its package drags in Perl for wrapper scripts we don't
# use, so only the binary and the libraries it links to are carried over.
FROM python:3.12-slim AS pg_dump
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17
RUN mkdir -p /opt/pg/bin /opt/pg/lib \
    && cp /usr/lib/postgresql/17/bin/pg_dump /opt/pg/bin/ \
    && ldd /opt/pg/bin/pg_dump | awk '/=> \// {print $3}' \
        | grep -vE '/(libc\.so|libm\.so|libresolv\.so|ld-linux)' \
        | xargs -I{} cp -L {} /opt/pg/lib/

# Dependencies go into a virtualenv of their own, without pip and setuptools.
FROM python:3.12-slim AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY app ./app
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install . \
    && /opt/venv/bin/pip uninstall -y vending-ops pip setuptools

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

COPY --from=deps /opt/venv /opt/venv
COPY --from=pg_dump /opt/pg /opt/pg
RUN printf '#!/bin/sh\nLD_LIBRARY_PATH=/opt/pg/lib exec /opt/pg/bin/pg_dump "$@"\n' \
        > /usr/local/bin/pg_dump \
    && chmod +x /usr/local/bin/pg_dump \
    && useradd --create-home --uid 1000 app

WORKDIR /srv
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
# Compiled once here instead of on every cold start of a serverless instance.
RUN python -m compileall -q app

USER app

CMD ["python", "-m", "app.bot"]
