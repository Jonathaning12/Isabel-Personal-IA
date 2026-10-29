# SUBMISSION.md

> Official hackathon rules (summarized from the organizers' text) and the submission checklist.
> Written in English because the submission is read by the judges. Keep it current: it feeds the submission form.

## 0. Key facts from the official Devpost rules page (https://nebiusglobalaihackathon.devpost.com/rules)
- **Deadline: Oct 30, 2026 @ 10:00 am PDT = Friday Oct 30, 11:00 CST (UTC-6, the student's time zone) = 17:00 UTC.** Plan to submit by Thursday night or Friday 09:00 CST at the latest.
- Judging: Dec 1–15, 2026. **The repo, the Release and the instructions must still work then.**
- **Personal AI track:** "build an always-on, private assistant that works for you while keeping your data under your control." A secondary source describes it as "a private, always-on assistant with **memory, reusable skills, and user-controlled tools**".
- **Judging criteria, weighted equally:** Technological Implementation · Design · Potential Impact · Quality of the Idea. Judges include engineers from NVIDIA and Nebius, and staff from Tavily.
- Demo URL: "a working demo, hosted application, or test build". The rules give no further detail, so a GitHub Release (test build) with clear instructions is our plan. Organizers have been asked.
- Source note: the rules page blocks automated reading. These facts come from the page's search snippet and a web search (2026-10-28); check them on the page before submitting.

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
| R3 | Text description of features and functionality | §4 below (final) | ✅ draft final |
| R4 | **Public** repo URL (GitHub/GitLab/Bitbucket) with all source, assets, instructions | https://github.com/javierrpdev/ai-personal-Assistant (private for now; make public before submitting, then check the license shows in About) | 🟡 pushed, private |
| R5 | **Open-source license file** detectable in the repo's About section | `LICENSE` (MIT) at the repo root | ✅ file added; verify on GitHub once public |
| R6 | README with setup instructions and clear run guidance | `README.md`: prerequisites, quickstart, usage, tests, `assistant doctor`, `scripts/demo_setup.sh` | ✅ (re-test on a clean clone before submitting) |
| R7 | README **highlights NVIDIA Nemotron usage**, **where Token Factory accelerated the workflow**, and any other Nebius tools | README section "How we use NVIDIA & Nebius" | ✅ |
| R8 | **Demo video < 3 min**, public on **YouTube**, showing the project running on its intended device; no third-party trademarks or copyrighted music | Screen recording of the terminal demo on the Mac; no music, or royalty-free only | ⬜ |
| R9 | Identify the track | **Personal AI Track** | ✅ |
| R10 | **Feedback** on Token Factory, AI Cloud, NVIDIA tools/models | §6 feedback log (fill in during development) | 🟡 logging |
| R11 | If pre-existing, explain what was updated | Not applicable (new project) | ✅ |

## 2. Implications for engineering
- **Judges must be able to install and run it.** The README must state the prerequisites explicitly: Docker, `uv`, and **their own Nebius API key** in `.env`. `uv sync` + `docker compose up -d` must work on a clean clone (already checked in Phase 1).
- **"Works as shown in the video":** record the video only from the final, committed version. Never show features that are not merged.
- **License compatibility:** project is MIT. Model licenses verified on their Hugging Face model cards (2026-10-28): Nemotron 3 Super = NVIDIA Nemotron Open Model License (commercial use allowed); Qwen3-Embedding-8B = Apache-2.0. Both are listed in the README.
- **Never commit `.env`** when the repo becomes public. Gitleaks pre-commit is active. Before making the repo public, run `uv run pre-commit run gitleaks --all-files` and scan the git history.

## 3. Demo URL (R2) — decision pending
The app is a **local terminal (CLI) app**: privacy comes from keeping storage local, so there is no public website. Options:
- **A (recommended): test build** = a GitHub **Release** (tagged version, e.g. `v1.0.0`) with install instructions. It runs with `docker compose up -d` + `uv run assistant chat`. Combined with the YouTube video, this covers "working demo or test build".
- **B: hosted demo** on Nebius AI Cloud (DevPod) with a minimal web chat page. Stronger "always-on" story, and uses one more Nebius service. Costs about 3–5 h, so only if organizers say a test build is not enough.
- Action: ask the organizers whether a GitHub Release (test build) is acceptable for a local CLI app.

## 4. Text description (final)
**Personal AI Assistant: private, agentic, human-in-the-loop.**

A personal AI assistant for the terminal that knows *your* life without uploading it to anyone's cloud. It ingests your notes and documents (Markdown, text, PDF) into a local vector database (Qdrant) and answers questions **citing the exact note** each fact came from. It says "I didn't find it" instead of inventing. It remembers your preferences across sessions, and you can list and delete what it knows.

It is a **LangGraph agent** powered by **NVIDIA Nemotron 3 Super (120B) on Nebius Token Factory**. It decides when to search your notes, remember a fact, or write and run Python code. Every action with side effects **pauses and asks for your approval**, showing the exact code and its limits. Approved code runs in a locked-down Docker sandbox: no network, no access to your files, read-only, non-root, with CPU, memory and time limits. Rejections are enforced in code, every decision is written to an audit log, and prompt-injection attempts in documents are flagged and cannot bypass approval.

Built with FastAPI, LangGraph, Qdrant and Docker. Tested with 53 unit and 12 integration tests, and a retrieval evaluation (recall@5 = 1.00 on paraphrased questions). All inference (chat and embeddings) runs on Nebius Token Factory; all storage stays local. MIT licensed.

## 5. README section "How we use NVIDIA & Nebius" (R7) — ✅ written
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
- 2026-10-28 · ⚠️ Nemotron 3 Super cites sources with full-width brackets (【1】, 【1†L3】) even when told to use [1]; we normalize them in code.
- 2026-10-28 · 👍 Nemotron 3 Super handled a prompt-injection attempt inside retrieved context well: it described the text and refused to follow it.
- 2026-10-28 · 👍 Qwen3-Embedding-8B on Token Factory gave recall@5 = 1.00 on our Spanish paraphrased test set; a 4096-dim vector in ~0.5 s per batch.
- 2026-10-28 · 👎 Embedding latency on Token Factory was highly variable in the afternoon/evening of 2026-10-28 (22:00–00:30 UTC): single-text `Qwen/Qwen3-Embedding-8B` requests took 1–26 s (median ~8 s), versus < 1 s the night before. Chat completions on Nemotron 3 Super stayed fast (1–2 s) at the same time. We added a query-embedding cache to soften it; a status page or published latency SLOs per model would help.
- 2026-10-28 · 👍 Nemotron 3 Super tool calling in an agent loop was reliable: correct tool choice for code, memory and chat, valid JSON arguments, and it respected rejected actions.
- 2026-10-28 · ℹ️ `/v1/models` exposes `shutdown_date` but no model type (chat vs embedding) or context length. Adding them would make model selection easier.
