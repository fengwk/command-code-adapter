FROM python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3 AS builder

WORKDIR /app

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --only main --no-cache

FROM python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3 AS runtime

WORKDIR /app

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY --from=builder $VIRTUAL_ENV $VIRTUAL_ENV

COPY pyproject.toml ./
COPY cc_adapter/ ./cc_adapter/

EXPOSE 8080

# The uid/gid are pinned so the image's file ownership is deterministic: a deployment
# that mounts a data directory either runs as this user or overrides `user:` (see the
# nas-aiproxy compose). `useradd -r` alone would take whatever the base image happens
# to leave free and silently drift on a base image update.
RUN groupadd -r -g 999 appuser && useradd -r -u 999 -g appuser -d /app -s /sbin/nologin appuser && \
    chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, cc_adapter.core.config as c; port = c.AppConfig().port; urllib.request.urlopen(f'http://localhost:{port}/health')" || exit 1

CMD ["python", "-m", "cc_adapter"]
