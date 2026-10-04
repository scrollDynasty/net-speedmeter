# syntax=docker/dockerfile:1

# --- build: resolve locked dependencies and install the project into a venv ---
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
# Dependencies first: this layer is cached until uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# --- runtime: just the interpreter and the venv, running as non-root ---
FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
COPY --from=build --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER app
# `docker stop` sends SIGINT => KeyboardInterrupt => partial summary instead of SIGKILL after 10 s
STOPSIGNAL SIGINT
ENTRYPOINT ["net-speedmeter"]
