# SUBMISSION.md

> Official hackathon rules (summarized from the organizers' text) and the submission checklist.
> Written in English because the submission is read by the judges. Keep it current: it feeds the submission form.

## 1. Official requirements (source: hackathon rules, received 2026-10-28)

### Project requirements
- A **working software application** that **runs on Nebius Token Factory or Nebius AI Cloud** and uses **at least one NVIDIA open-source model**, fitting one of the four tracks.
- "Runs on Nebius" = the project makes a **runtime call to the Token Factory inference API**, *or* is deployed/run on Nebius AI Cloud compute (Serverless Jobs, Serverless Endpoints, DevPods).
- **Functionality:** must install and run consistently on its intended platform, and must work exactly as shown in the video and described in the text.
- **New & existing:** newly created during the submission period (our case: repo started 2026-10-27).
- **Third-party integrations:** we must be authorized to use every SDK, API, model, and dataset under its license.

### Submission requirements
| # | Requirement | Our plan | Status |
|---|---|---|---|
| R1 | Project built with the required tools and meets the project requirements | Nemotron 3 Super on Token Factory (runtime calls) | ✅ in progress |
| R2 | **URL to a working demo, hosted app, or test build** | See §3 (decision pending) | ⬜ |
| R3 | Text description of features and functionality | §4 draft below | ⬜ |
| R4 | **Public** repo URL (GitHub/GitLab/Bitbucket) with all source, assets, instructions | GitHub, public before submitting | ⬜ |
| R5 | **Open-source license file** detectable in the repo's About section | `LICENSE` at the repo root (MIT or Apache-2.0) | ⬜ |
| R6 | README with setup instructions and clear run guidance | `README.md` quickstart, tested on a clean clone | 🟡 basic version exists |
| R7 | README **highlights NVIDIA Nemotron usage**, **where Token Factory accelerated the workflow**, and any other Nebius tools | Dedicated README section (§5 below) | ⬜ |
| R8 | **Demo video < 3 min**, public on **YouTube**, showing the project running on its intended device; no third-party trademarks or copyrighted music | Screen recording of the terminal demo on the Mac; no music, or royalty-free only | ⬜ |
| R9 | Identify the track | **Personal AI Track** | ✅ |
| R10 | **Feedback** on Token Factory, AI Cloud, NVIDIA tools/models | §6 feedback log (fill in during development) | 🟡 logging |
| R11 | If pre-existing, explain what was updated | Not applicable (new project) | ✅ |

## 2. Implications for engineering
- **Judges must be able to install and run it.** The README must state the prerequisites explicitly: Docker, `uv`, and **their own Nebius API key** in `.env`. `uv sync` + `docker compose up -d` must work on a clean clone (already checked in Phase 1).
- **"Works as shown in the video":** record the video only from the final, committed version. Never show features that are not merged.
- **License compatibility:** choose a permissive license (MIT/Apache-2.0). Record the model licenses in the README: Nemotron (NVIDIA Open Model License) and Qwen3-Embedding-8B (verify license on its model card before submitting).
- **Never commit `.env`** when the repo becomes public. Gitleaks pre-commit is active. Before making the repo public, run `uv run pre-commit run gitleaks --all-files` and scan the git history.

## 3. Demo URL (R2) — decision pending
The app is a **local terminal (CLI) app**: privacy comes from keeping storage local, so there is no public website. Options:
- **A (recommended): test build** = a GitHub **Release** (tagged version, e.g. `v1.0.0`) with install instructions. It runs with `docker compose up -d` + `uv run assistant chat`. Combined with the YouTube video, this covers "working demo or test build".
- **B: hosted demo** on Nebius AI Cloud (DevPod) with a minimal web chat page. Stronger "always-on" story, and uses one more Nebius service. Costs about 3–5 h, so only if organizers say a test build is not enough.
- Action: ask the organizers whether a GitHub Release (test build) is acceptable for a local CLI app.

## 4. Text description (draft, finalize in Phase 4)
*Private, always-on personal AI assistant for the terminal. It ingests your notes and documents into a local vector database (Qdrant), answers questions with citations, remembers facts about you across sessions, and can write and run small Python scripts in an isolated Docker sandbox — always asking for your approval first. All reasoning runs on NVIDIA Nemotron 3 Super via Nebius Token Factory; all storage stays on your machine.*

## 5. README section to write: "How we use NVIDIA & Nebius" (R7)
Points to cover:
- **Nemotron 3 Super 120B** (`nvidia/nemotron-3-super-120b-a12b`): every answer, every agent decision, every tool call. Reasoning toggled per task (on for agent decisions, off for routing and extraction).
- **Token Factory**: an OpenAI-compatible API, so the official `openai` SDK works by changing only the base URL. No GPU management. We compared 4 Nemotron models in minutes through one API (catalog check + tool-calling + latency test).
- **Embeddings on Token Factory**: `Qwen/Qwen3-Embedding-8B` (the only embedding model in the catalog).
- Any other Nebius service we end up using (e.g. AI Cloud DevPod if option B is chosen).

## 6. Feedback log for Nebius / NVIDIA (R10)
Write down real friction and praise as it happens. Facts only, with dates.
- 2026-10-28 · 👍 Token Factory is OpenAI-compatible: the official SDK worked with only a base-URL change; first successful call within minutes.
- 2026-10-28 · 👍 `GET /v1/models` makes catalog verification easy; tool calling worked on all 4 Nemotron models tested.
- 2026-10-28 · 👎 Many examples and guides still reference `Llama-3.1-Nemotron-70B-Instruct` and `NV-Embed-v1`, but neither is in the current catalog. We had to find replacements ourselves.
- 2026-10-28 · 👎 No NVIDIA embedding model is available on Token Factory; only `Qwen/Qwen3-Embedding-8B`. An NVIDIA embedder would allow a full NVIDIA stack.
- 2026-10-28 · ⚠️ Nemotron 3 reasoning tokens count against `max_tokens`: with a small limit, the answer comes back empty (`content=None`, `finish_reason=length`). The `enable_thinking` switch (`chat_template_kwargs`) works but is hard to find. Clearer docs would help.
- 2026-10-28 · ℹ️ `/v1/models` exposes `shutdown_date` but no model type (chat vs embedding) or context length. Adding them would make model selection easier.
