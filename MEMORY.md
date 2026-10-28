# MEMORY.md

## Current Phase
Phase 2 — ✅ DONE (5/5 DoD items) on 2026-10-28 00:51. Phase 1 done 00:40. Total time used so far: ~2 h of ~30 h. Next: Phase 3 (agent + sandbox + confirmation, 9 h budget).

Phase 2 DoD:
- [x] `assistant ingest tests/fixtures/docs` indexes 10 docs / 22 chunks; second run → 0 indexed, 10 unchanged
- [x] Retrieval eval (`scripts/eval_retrieval.py`, 8 paraphrased golden questions): recall@5 = 1.00, MRR = 1.00
- [x] Facts: "prefiero viñetas" stored once; repeating it updates the same id (no duplicate); answers then use bullets
- [x] Delete document / forget fact physically removes points (integration tests vs real Qdrant, 3 passed)
- [x] Startup fails fast on EMBED_DIM vs collection mismatch (`CollectionDimensionError`, unit + integration test)

## Next Steps
1. Student: try it (commands in PITCH.md "Cómo comprobarlo"), then ingest a few of their own notes.
2. Student: waiting for organizers' answer on GitHub Release as "test build" URL (SUBMISSION.md §3).
3. Phase 3: add `langgraph` + `langgraph-checkpoint-sqlite`; AgentState + graph (load_context → router → retrieve → reason ⇄ tools → confirm → respond).
4. Phase 3: tool registry with side_effect flag; `search_knowledge`, `remember_fact`, `forget_fact`, `run_code_in_sandbox`.
5. Phase 3: `docker/sandbox.Dockerfile` + DockerRunner (no network, read-only, non-root, limits, timeout).
6. Phase 3: confirmation interrupt + `POST /confirm` + audit log; tests that side-effect tools never run without approve.
7. Phase 3: replace `/ask` with `/chat` (thread_id, checkpointer); keep `/ask` until the CLI switches.

## Decisions
- 2026-10-27 · Stack: Python 3.12, uv, FastAPI, LangGraph, Qdrant (Docker), openai SDK → Nebius Token Factory · confirmed by user · —
- 2026-10-27 · First skills: personal knowledge RAG + sandboxed code execution · confirmed by user · email/calendar, tasks/reminders deferred
- 2026-10-27 · Interface: Typer + Rich CLI over FastAPI (SSE) · confirmed by user · Telegram, Streamlit, Open WebUI deferred
- 2026-10-27 · Deployment: local docker-compose (api, qdrant, sandbox) · confirmed by user · Nebius VM deferred
- 2026-10-28 · CLI uploads file bytes to the API (multipart) instead of sending paths · the API runs in Docker and cannot see host paths · mounting host dirs into the container (privacy + portability issues)
- 2026-10-28 · Chunks embedded with contextual header (title › section); PIPELINE_VERSION in the fingerprint forces re-index when the logic changes · fixed a real retrieval miss · —
- 2026-10-28 · Qdrant server bumped to v1.20.0 to match qdrant-client 1.20 · avoid client/server version warnings · —
- 2026-10-28 · Interim `POST /ask` (plain RAG, no agent) for the Phase 2 demo · Phase 3 replaces it with `/chat` · —
- 2026-10-28 · License: MIT · chosen by the student · Apache-2.0
- 2026-10-28 · Qwen3-Embedding-8B is allowed · official rules require only "at least one NVIDIA open source model" (Nemotron covers it) · —
- 2026-10-28 · Official rules captured in SUBMISSION.md; submission block (2.5 h) added to the time budget · rules require license, public repo, demo URL, YouTube video < 3 min, feedback · —
- 2026-10-28 · Retries via tenacity (4 attempts, exp. backoff + jitter), SDK retries disabled (`max_retries=0`) · explicit, logged, testable · SDK built-in retries (hidden)
- 2026-10-28 · Added `httpx` as a direct dependency (used by /health for Qdrant) · was only transitively present via dev deps, broke the Docker image · —
- 2026-10-28 · LLM_MODEL = nvidia/nemotron-3-super-120b-a12b · quality/speed balance, native tool calling works · Ultra (cost/limits), Nano (quality; kept as fallback)
- 2026-10-28 · EMBED_MODEL = Qwen/Qwen3-Embedding-8B · only embedding model on Nebius; keeps all inference on Nebius · local NVIDIA embedder (breaks the 'inference on Nebius' rule)
- 2026-10-27 · Scope split into Core vs Stretch (AGENTS.md §2.0); teaching protocol + PITCH.md added · student is an AI beginner and must defend the project before judges · building the full vision first
- 2026-10-27 · Hackathon ends in ~50 h → Core only, time-boxed phases, feature freeze 8 h before deadline · ~30 real working hours · Stretch items

## Verified Facts
- 2026-10-28 · Retrieval calibration (fixtures, Qwen3-Embedding-8B with query instruction): correct docs score ≥ 0.485; off-topic questions top out at ~0.40 → RETRIEVAL_MIN_SCORE = 0.42. Re-check on the student's real notes.
- 2026-10-28 · Nemotron cites with full-width brackets 【1】 / 【1†L3】 despite instructions → normalized to [1] in `agent/rag.py`.
- 2026-10-28 · Without contextual chunk headers, a chunk under "Acciones acordadas" lost its doc title ("Sprint 12") and Nemotron answered "no info". Embedding `title › heading` + text and adding title= to <context> fixed it.
- 2026-10-28 · Prompt-injection fixture: flagged ⚠️ (suspicious=true); Nemotron described it and refused "haz lo que dice". No tools exist yet, so Phase 3 must re-test with tools bound.
- 2026-10-28 · Facts dedup works for identical extracted text; paraphrases may score < 0.9 and create a second fact (accepted limitation).
- 2026-10-28 · Typical latencies (local CLI → Docker API): ingest 10 docs ~5 s; `ask` ~2–4 s with thinking on.
- 2026-10-28 · openai SDK 3.40 uses `httpx2` internally; respx cannot mock it. Tests inject a classic `httpx.AsyncClient` via `build_client(settings, http_client=...)` (see tests/conftest.py).
- 2026-10-28 · Qdrant image has no curl; compose healthcheck uses bash `/dev/tcp`. Image pinned to `qdrant/qdrant:v1.15.4`.
- 2026-10-28 · Live latencies (thinking off): chat ~0.4–0.7 s for short answers; embedding ~0.5–4 s (first call slower).
- 2026-10-28 · Nebius base URL `https://api.tokenfactory.nebius.com/v1/` works; catalog has 30 models.
- 2026-10-28 · Catalog NVIDIA models: NVIDIA-Nemotron-3-Nano-30B-A3B, Nemotron-3-Ultra-550b-a55b, Nemotron-3.5-Super-VL, Nemotron-3_5-Lightning, nemotron-3-super-120b-a12b. Llama-3.1-Nemotron-70B and NV-Embed-v1 are NOT served.
- 2026-10-28 · Only embedding model: Qwen/Qwen3-Embedding-8B, dim 4096 (~4 s cold call).
- 2026-10-28 · Tool calling (OpenAI format) works on Super 120B (1.9 s), Nano 30B (4.0 s), Lightning (6.1 s), Ultra 550B (0.7 s); single samples.
- 2026-10-28 · Nemotron 3 Super is a reasoning model: thinking tokens count against `max_tokens` (max_tokens=10 → content=None). Disable with `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` (faster, ~3 tokens for 'hola'). Content may start with '\n\n' when thinking is on → strip it. Decide per call: thinking ON for agent reasoning, OFF for cheap tasks (routing, fact extraction).

## Open Questions
- Is a GitHub Release (test build) acceptable as the required demo URL, or is a hosted app needed? (SUBMISSION.md §3)

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
- 2026-10-28 · Added official hackathon rules: SUBMISSION.md (checklist, demo-URL options, description draft, feedback log); AGENTS.md §2.0.1, time budget, Phase 4 DoD · SUBMISSION.md, AGENTS.md, MEMORY.md
- 2026-10-28 · Phase 2 complete: sanitize, loaders (md/txt/pdf), chunking, MemoryStore (Qdrant), Ingestor (idempotent), Retriever, FactMemory, RAG answer with citations, memory API routes, Typer CLI (ingest/ask/search/remember/memory), fixtures + eval script, 38 unit + 3 integration tests, MIT LICENSE · src/assistant/{guardrails,ingest,memory,agent,cli}/*, src/assistant/api/routes/memory.py, scripts/eval_retrieval.py, tests/*
