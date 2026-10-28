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

## Usage

```bash
uv run assistant ingest path/to/notes        # index .md / .txt / .pdf files
uv run assistant ask "What is my budget for the trip?"
uv run assistant remember "I prefer answers in bullet points"
uv run assistant memory facts                # what the assistant knows about you
uv run assistant memory docs                 # indexed documents
uv run assistant --help
```

Try it with the synthetic sample notes in `tests/fixtures/docs/`.

## Tests

```bash
uv run pytest -q          # unit tests (Nebius mocked)
uv run pytest -q -m live         # real calls to Nebius (uses .env)
uv run pytest -q -m integration  # real Qdrant (docker compose up -d qdrant)
uv run python scripts/eval_retrieval.py  # retrieval quality (recall@5, MRR)
```

## License

MIT — see `LICENSE`.

See `AGENTS.md` for the architecture and development plan.
