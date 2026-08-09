# Multi-stage build: uv resolves/installs into a venv in the builder stage,
# the runtime stage copies only that venv + source — no compiler toolchain
# or uv itself ships in the final image.
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Dependencies first so the layer caches across source-only changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --locked --no-dev

FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app
EXPOSE 8000

# Migrations run as an explicit Coolify/compose pre-deploy command, not
# baked into this CMD — running them on every container start would race
# when the service scales beyond one replica.
CMD ["uvicorn", "content_studio.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
