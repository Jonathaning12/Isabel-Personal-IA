# MEMORY.md

## Current Phase
Phase 1 — ✅ DONE (6/6 DoD items) on 2026-10-28 ~00:40. Time used: ~1.5 h of the 4 h budget (total ~1.5 h of ~30 h). Next: Phase 2 (memory + RAG, 7 h budget).

Phase 1 DoD:
- [x] `uv sync` on a clean clone; `docker compose up -d` → api + qdrant healthy
- [x] `verify_models.py` prints confirmed models (see Verified Facts)
- [x] Unit tests with respx: success, 429 retry, timeout, 4xx no-retry (+ batching, dim mismatch, /health)
- [x] Live test (`pytest -m live`): real chat, stream, and embedding → 2 passed
- [x] `GET /health` → 200, nebius ok, qdrant ok
- [x] Pre-commit gitleaks passes; verified it blocks a fake staged key

## Next Steps
1. Student (morning): run the 3 check commands in PITCH.md "Cómo comprobarlo" and read the new glossary entries.
2. Student: confirm with organizers (Discord) that Qwen3-Embedding-8B is acceptable for embeddings.
3. Phase 2: add `qdrant-client`; `memory/store.py` with collection bootstrap + dimension check.
4. Phase 2: loaders (md, txt, pdf) → sanitize → chunking → embed → upsert (sha256 idempotency).
5. Phase 2: synthetic fixture notes (~10) + 8 golden questions; retrieval eval (recall@5 ≥ 0.75).
6. Phase 2: `user_facts` remember/forget + API routes.

## Decisions
- 2026-10-27 · Stack: Python 3.12, uv, FastAPI, LangGraph, Qdrant (Docker), openai SDK → Nebius Token Factory · confirmed by user · —
- 2026-10-27 · First skills: personal knowledge RAG + sandboxed code execution · confirmed by user · email/calendar, tasks/reminders deferred
- 2026-10-27 · Interface: Typer + Rich CLI over FastAPI (SSE) · confirmed by user · Telegram, Streamlit, Open WebUI deferred
- 2026-10-27 · Deployment: local docker-compose (api, qdrant, sandbox) · confirmed by user · Nebius VM deferred
- 2026-10-28 · Retries via tenacity (4 attempts, exp. backoff + jitter), SDK retries disabled (`max_retries=0`) · explicit, logged, testable · SDK built-in retries (hidden)
- 2026-10-28 · Added `httpx` as a direct dependency (used by /health for Qdrant) · was only transitively present via dev deps, broke the Docker image · —
- 2026-10-28 · LLM_MODEL = nvidia/nemotron-3-super-120b-a12b · quality/speed balance, native tool calling works · Ultra (cost/limits), Nano (quality; kept as fallback)
- 2026-10-28 · EMBED_MODEL = Qwen/Qwen3-Embedding-8B · only embedding model on Nebius; keeps all inference on Nebius · local NVIDIA embedder (breaks the 'inference on Nebius' rule)
- 2026-10-27 · Scope split into Core vs Stretch (AGENTS.md §2.0); teaching protocol + PITCH.md added · student is an AI beginner and must defend the project before judges · building the full vision first
- 2026-10-27 · Hackathon ends in ~50 h → Core only, time-boxed phases, feature freeze 8 h before deadline · ~30 real working hours · Stretch items

## Verified Facts
- 2026-10-28 · openai SDK 3.40 uses `httpx2` internally; respx cannot mock it. Tests inject a classic `httpx.AsyncClient` via `build_client(settings, http_client=...)` (see tests/conftest.py).
- 2026-10-28 · Qdrant image has no curl; compose healthcheck uses bash `/dev/tcp`. Image pinned to `qdrant/qdrant:v1.15.4`.
- 2026-10-28 · Live latencies (thinking off): chat ~0.4–0.7 s for short answers; embedding ~0.5–4 s (first call slower).
- 2026-10-28 · Nebius base URL `https://api.tokenfactory.nebius.com/v1/` works; catalog has 30 models.
- 2026-10-28 · Catalog NVIDIA models: NVIDIA-Nemotron-3-Nano-30B-A3B, Nemotron-3-Ultra-550b-a55b, Nemotron-3.5-Super-VL, Nemotron-3_5-Lightning, nemotron-3-super-120b-a12b. Llama-3.1-Nemotron-70B and NV-Embed-v1 are NOT served.
- 2026-10-28 · Only embedding model: Qwen/Qwen3-Embedding-8B, dim 4096 (~4 s cold call).
- 2026-10-28 · Tool calling (OpenAI format) works on Super 120B (1.9 s), Nano 30B (4.0 s), Lightning (6.1 s), Ultra 550B (0.7 s); single samples.
- 2026-10-28 · Nemotron 3 Super is a reasoning model: thinking tokens count against `max_tokens` (max_tokens=10 → content=None). Disable with `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` (faster, ~3 tokens for 'hola'). Content may start with '\n\n' when thinking is on → strip it. Decide per call: thinking ON for agent reasoning, OFF for cheap tasks (routing, fact extraction).

## Open Questions
- Organizers' confirmation that a non-NVIDIA embedding model (Qwen3-Embedding-8B on Nebius) is acceptable.

## Known Issues / Tech Debt
- Logging uses stdlib `logging` (key=value format) instead of `structlog` from AGENTS.md §2.4. Good enough for the hackathon; switch only if time remains.
- `/health` calls Nebius `models.list` on every request (no caching); fine for local use.
- `OpenShellRunner` is planned as a stub only.

## Changelog
- 2026-10-27 · Created AGENTS.md (spec) and MEMORY.md (seed) · AGENTS.md, MEMORY.md
- 2026-10-27 · Added student/teaching protocol, Core vs Stretch scope, PITCH.md spec · AGENTS.md, MEMORY.md
- 2026-10-27 · Added 50 h time budget and reduced DoD targets (AGENTS.md §4.0) · AGENTS.md, MEMORY.md
- 2026-10-28 · Phase 1 skeleton: uv project (Python 3.12), Settings, .env.example, .gitignore, verify_models.py · pyproject.toml, src/assistant/config.py, scripts/verify_models.py
- 2026-10-28 · Verified catalog, chose models, updated .env/.env.example/AGENTS.md, created PITCH.md · .env.example, AGENTS.md, PITCH.md
- 2026-10-28 · Phase 1 complete: Nebius client + retries, ChatClient (complete/stream, thinking toggle), Embedder (batched, dim check), /health, docker-compose (api+qdrant), api Dockerfile, pre-commit (ruff+gitleaks), 8 unit + 2 live tests · src/assistant/llm/*, src/assistant/api/*, docker/, docker-compose.yml, tests/*
