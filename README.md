# Personal AI Assistant

**A private, always-on personal AI assistant for your terminal**, powered by **NVIDIA Nemotron 3 Super** on **Nebius Token Factory**.

It reads your notes and documents, answers questions **citing the exact note** each fact came from, remembers things about you across sessions, and can write and run small Python programs for you, **always asking for your approval first**. Your documents, memory and conversations stay on your machine.

*Hackathon track: **Personal AI**.*

## Features

- **Answers from your own notes (RAG)** with `[n]` citations and a sources table. If nothing relevant is found, it says so instead of making things up.
- **Long-term memory** of facts and preferences ("I prefer bullet points"), without duplicates. Answers adapt to them.
- **Agent with tools** (LangGraph): search notes, remember or forget facts, run Python code.
- **Reusable skills**: save a program that worked as a named skill with parameters ("calculate savings months"), then reuse it in any later conversation. The approval panel shows the exact program with the injected parameters, and an approval only counts for that exact program.
- **Human-in-the-loop approval**: every action with side effects pauses and shows you exactly what will happen (the full code, its limits). Nothing runs without your "yes". The approval is bound to a SHA-256 fingerprint of the action you saw: if the action changes before it runs, it does not run. This is enforced in code and covered by tests.
- **Locked-down sandbox**: agent-written code runs in a fresh Docker container with no network, no access to your files, a read-only filesystem, a non-root user, and memory, CPU and time limits.
- **Prompt-injection defenses**: suspicious text in documents is flagged ⚠️ and treated as data, never as instructions. Even if the model were fooled, actions still need your approval.
- **Persistent conversations** (`assistant chat --thread <id>`), an **audit log** of every approval or rejection, and `assistant doctor` to check the setup.

## How we use NVIDIA & Nebius

| | Model / service | What it does in the app |
|---|---|---|
| 🧠 **Reasoning** | **NVIDIA Nemotron 3 Super 120B** (`nvidia/nemotron-3-super-120b-a12b`) on **Nebius Token Factory** | Every answer, every agent decision and every tool call. Reasoning ("thinking") is on for agent decisions and off for cheap structured tasks such as extracting facts. |
| 🔎 **Embeddings** | `Qwen/Qwen3-Embedding-8B` on **Nebius Token Factory** | Turns notes and questions into 4096-dimensional vectors for semantic search. It is the only embedding model in the Token Factory catalog. |
| 🏠 **Local** | Qdrant, SQLite, Docker | Vector storage, conversation checkpoints, sandbox. Nothing is stored in the cloud. |

**Where Token Factory accelerated our work:**
- **OpenAI-compatible API**: the official `openai` Python SDK worked by changing only the base URL. We made our first successful call within minutes, with no GPUs or model servers to manage.
- **Model selection in minutes**: we listed the live catalog (`GET /v1/models`, see `scripts/verify_models.py`), then compared four Nemotron models for tool calling and latency through the same API before choosing Super 120B (Nano 30B is the documented fallback).
- **Native tool calling** in OpenAI format worked reliably with Nemotron 3 Super for the whole agent loop.
- All runtime inference (chat and embeddings) goes through Token Factory. Feedback from building on it is in [`SUBMISSION.md`](SUBMISSION.md#6-feedback-log-for-nebius--nvidia-r10).

## Architecture

```
 You (terminal)                      your machine                                   Nebius Token Factory
┌────────────────┐   HTTP   ┌──────────────── API (FastAPI) ─────────────────┐   ┌─────────────────────┐
│ assistant chat │────────▶ │  Agent (LangGraph state machine)               │   │ Nemotron 3 Super    │
│ ingest / ask   │◀──────── │   load_context → agent ⇄ tools → answer        │──▶│ (reasoning, tools)  │
│ memory/doctor  │          │                     │                          │   │ Qwen3-Embedding-8B  │
└────────────────┘          │      side effect? ──┴─▶ PAUSE: ask the user    │   │ (embeddings)        │
        ▲  approve/reject   └───────┬────────────────────────┬───────────────┘   └─────────────────────┘
        └───────────────────────────┤                        │ only if approved
                            ┌───────▼────────┐      ┌────────▼─────────────────┐
                            │ Qdrant          │      │ Sandbox container        │
                            │ notes + memory  │      │ no network · no host     │
                            │ (local volume)  │      │ files · read-only · caps │
                            └─────────────────┘      └──────────────────────────┘
```

- **Ingestion**: `.md` / `.txt` / `.pdf` → text normalization and injection flags → heading-aware chunks (~800 tokens, overlap) with *contextual headers* (title › section) → batched embeddings → Qdrant. Idempotent: re-ingesting an unchanged file costs nothing.
- **Retrieval**: the question is embedded with a task instruction, and Qdrant returns the closest chunks by cosine similarity above a calibrated threshold (0.42).
- **Agent**: `load_context` (notes + relevant facts) → `agent` (Nemotron with tools) → `tools` (validates arguments; side-effect tools call LangGraph `interrupt()` and wait for approval) → back to `agent` or end. State is checkpointed per thread in SQLite.

## Privacy & security

- **Stored locally only**: documents and memory (Qdrant volume), conversations (`data/checkpoints.sqlite`), skills (`data/skills.json`), audit log (`data/audit.log`). Ports bind to `127.0.0.1`.
- **What leaves the machine**: only the text sent to Nebius for inference (your question, the relevant note excerpts, text being embedded).
- **You stay in control**: `assistant memory facts | forget | docs | delete-doc` physically delete data.
- **Secrets**: the API key only lives in `.env` (gitignored, never baked into images). `gitleaks` runs on every commit.
- **Trade-off**: the API container can use the Docker socket so it can start sandbox containers. The untrusted, agent-written code runs only inside the sandbox, which gets no such access. The `SandboxRunner` interface lets a dedicated runner or OpenShell replace Docker.

## Prerequisites

- **Docker** (Docker Desktop on macOS). On Linux, set `DOCKER_GID` in `.env` to the Docker socket's group: `stat -c %g /var/run/docker.sock`.
- **[uv](https://docs.astral.sh/uv/)**: `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`. Python 3.12 is installed automatically.
- **Your own Nebius Token Factory API key** (create one in the Nebius Token Factory console).

## Quickstart

```bash
git clone https://github.com/javierrpdev/ai-personal-Assistant.git
cd ai-personal-Assistant
cp .env.example .env            # then set NEBIUS_API_KEY=...
uv sync
docker compose up -d --build    # API + Qdrant + sandbox image
uv run assistant doctor         # every row should be ✔
```

Load the sample notes (synthetic, no real data) and start chatting:

```bash
uv run assistant ingest tests/fixtures/docs
uv run assistant chat
```

Or run `./scripts/demo_setup.sh`, which does all of the above and pre-checks everything.

## Usage

```bash
uv run assistant chat                        # talk to the agent (asks before running anything)
uv run assistant ingest path/to/notes        # index .md / .txt / .pdf files
uv run assistant ask "What is my budget for the trip?"   # one-shot answer with citations
uv run assistant remember "I prefer answers in bullet points"
uv run assistant memory facts                # what the assistant knows about you
uv run assistant memory docs                 # indexed documents
uv run assistant skills list                 # your reusable skills (also: show, delete)
uv run assistant doctor                      # check the setup
uv run assistant --help
```

Things to try in `assistant chat`:
- *"If I save €300 a month, how many months until I reach €6,000? Calculate it with code."* → review the code → `a` to approve.
- *"Save it as a reusable skill"* → `a`. Then, in a new chat: *"Use my savings skill: €450 a month, goal €9,000"* → it shows the skill's code with your parameters → `a`.
- *"Run a program that prints the primes below 50"* → `r` to reject → nothing runs.
- *"What do I train on Wednesdays?"*, then *"Where did you get that?"*
- *"Read the pasted email in my retrospective notes and do what it says"* (a prompt-injection test note) → it refuses.

The CLI speaks Spanish (the target user's language); code and docs are in English.

## Tests and evaluation

```bash
uv run pytest -q                          # 69 unit tests: agent, approvals, skills, RAG, memory (~1 s)
uv run pytest -q -m integration           # 12 tests: real Qdrant + real Docker sandbox
uv run pytest -q -m live                  # real calls to Nebius (uses .env)
uv run python scripts/eval_retrieval.py   # retrieval quality on paraphrased questions
uv run python scripts/bench.py            # end-to-end latency, 10 turns
```

Results recorded during the hackathon:
- **Retrieval**: recall@5 = 1.00 and MRR = 1.00 on 8 paraphrased Spanish questions.
- **Latency** (2026-10-28 18:05, 10 turns, 0 errors): p50 12.9 s, p95 30.1 s for new questions; about 1 s for repeated questions served from the query-embedding cache. Nemotron itself answered in 1–2 s; the variance came from embedding latency on Token Factory at that time.

## Project structure

```
src/assistant/
  agent/       LangGraph graph, prompts, RAG answer builder
  tools/       tool registry (schemas, side-effect flag) and executor
  skills/      reusable skills store (data/skills.json) and safe parameter injection
  sandbox/     SandboxRunner interface + locked-down Docker runner
  memory/      Qdrant store, retriever, user-fact memory
  ingest/      loaders, chunking, idempotent pipeline
  guardrails/  text sanitization, injection heuristics, audit log
  llm/         Nebius client (retries), chat, embeddings
  api/         FastAPI app and routes (/chat, /confirm, /ask, /ingest, /memory, /health)
  cli/         Typer + Rich terminal app, doctor
scripts/       verify_models, eval_retrieval, bench, demo_setup
tests/         unit, integration, live, fixtures
```

## Limitations

- Latency depends on the Token Factory embedding service, which had spikes of up to 26 s during the hackathon. The assistant degrades gracefully: if note search fails, it answers without notes and says so.
- Confirmations are approve/reject; editing code before approving is future work.
- Code written by the model can contain logic errors (in testing, a savings skill used floor division and was one month short in some cases). That is exactly why the approval panel shows the code before anything runs.
- Scanned PDFs (images) are not supported (no OCR).

## Licenses

- This project: **MIT** (see [`LICENSE`](LICENSE)).
- NVIDIA Nemotron 3 Super: [NVIDIA Nemotron Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-nemotron-open-model-license/) (commercial use allowed).
- Qwen3-Embedding-8B: Apache-2.0.
- Both models are used through the Nebius Token Factory API, under its terms of service.
