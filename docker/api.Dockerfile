# API image. Secrets are NOT baked in: docker-compose passes .env at runtime.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# git: the assistant's project tools (status, diff, commit, push) run it on mounted repos.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cached layer), then the project itself.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# Run as a non-root user.
RUN useradd --uid 10001 --create-home app && chown -R app /app
USER app

EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "assistant.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
