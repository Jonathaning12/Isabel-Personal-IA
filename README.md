# Personal AI Assistant

Private, always-on personal AI assistant powered by NVIDIA Nemotron models on Nebius Token Factory.
Storage (documents, vectors, memory) stays on your machine; only inference calls go to Nebius.

## Quickstart

```bash
cp .env.example .env              # then set NEBIUS_API_KEY
uv sync
uv run python scripts/verify_models.py
docker compose up -d
curl http://127.0.0.1:8000/health
```

## Tests

```bash
uv run pytest -q          # unit tests (Nebius mocked)
uv run pytest -q -m live  # real calls to Nebius (uses .env)
```

See `AGENTS.md` for the architecture and development plan.
