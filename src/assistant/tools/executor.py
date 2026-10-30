"""Execute an already-validated (and, if needed, already-approved) tool call."""

import asyncio
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from assistant.config import Settings
from assistant.memory.facts import FactMemory
from assistant.memory.retrieval import Retriever
from assistant.sandbox.base import SandboxRunner
from assistant.sandbox.docker_runner import SandboxError
from assistant.skills.store import Skill, SkillError, SkillStore, build_program
from assistant.tools.registry import (
    CreateFolderArgs,
    DeleteSkillArgs,
    FindFilesArgs,
    ForgetFactArgs,
    GitCommitArgs,
    ListNotesArgs,
    ReadNoteArgs,
    RememberFactArgs,
    RepoArgs,
    RunCodeArgs,
    RunSkillArgs,
    SaveSkillArgs,
    SearchKnowledgeArgs,
    SearchNotesArgs,
    WeatherArgs,
    WebSearchArgs,
    WriteNoteArgs,
)
from assistant.tools.web import WebError, get_weather, web_search
from assistant.vault.notes import Vault, VaultError
from assistant.workspace.projects import Workspace, WorkspaceError

PROJECT_TOOLS = {
    "list_projects",
    "git_status",
    "git_diff",
    "git_commit",
    "git_push",
    "create_folder",
    "find_files",
    "repos_overview",
}
NO_PROJECTS = {
    "status": "error",
    "error": "No projects folder is configured. Tell the user to set PROJECTS_HOST in .env "
    "and restart with docker compose up -d.",
}

NOTES_PREFIX = "obsidian/"  # source path of vault notes in the semantic index
NO_VAULT = {
    "status": "error",
    "error": "No Obsidian vault is configured. Tell the user to set OBSIDIAN_VAULT in .env "
    "and restart with docker compose up -d.",
}


class SupportsIngest(Protocol):
    async def ingest(self, source_path: str, data: bytes) -> Any: ...


@dataclass
class ToolOutput:
    result: dict[str, Any]
    new_citations: list[dict[str, Any]]


class ToolExecutor:
    def __init__(
        self,
        retriever: Retriever,
        facts: FactMemory,
        sandbox: SandboxRunner,
        skills: SkillStore,
        vault: Vault | None = None,
        ingestor: SupportsIngest | None = None,
        workspace: Workspace | None = None,
        settings: Settings | None = None,
    ):
        self._workspace = workspace
        self._settings = settings
        self._retriever = retriever
        self._facts = facts
        self._sandbox = sandbox
        self._skills = skills
        self._vault = vault
        self._ingestor = ingestor

    async def _projects(self, name: str, args: BaseModel) -> dict[str, Any]:
        ws = self._workspace
        assert ws is not None
        if name == "list_projects":
            return await asyncio.to_thread(ws.list_projects)
        if isinstance(args, CreateFolderArgs):
            return await asyncio.to_thread(ws.create_folder, args.path)
        if isinstance(args, FindFilesArgs):
            return {"files": await asyncio.to_thread(ws.find_files, args.query, args.extension)}
        if name == "repos_overview":
            return {"repos": await ws.repos_overview()}
        if isinstance(args, GitCommitArgs):
            return await ws.commit(args.repo, args.message)
        assert isinstance(args, RepoArgs)
        if name == "git_status":
            return await ws.status(args.repo)
        if name == "git_diff":
            return await ws.diff(args.repo)
        return await ws.push(args.repo)  # git_push

    async def _notes(self, name: str, args: BaseModel) -> dict[str, Any]:
        vault = self._vault
        assert vault is not None
        # File I/O runs in a worker thread: a big vault on a slow bind mount must never
        # freeze the API's event loop (chat, health checks, approvals).
        if isinstance(args, ListNotesArgs):
            notes = await asyncio.to_thread(vault.list_notes, args.folder, args.query)
            return {"notes": [asdict(n) for n in notes]}
        if isinstance(args, ReadNoteArgs):
            return await asyncio.to_thread(vault.read, args.path)
        if isinstance(args, SearchNotesArgs):
            return {"matches": await asyncio.to_thread(vault.search, args.text)}
        if isinstance(args, WriteNoteArgs):
            written = await asyncio.to_thread(vault.write, args.path, args.content, args.mode)
            # Keep the semantic index in step with the note that just changed. The note is
            # already saved, so an indexing failure (e.g. slow embeddings) is only reported.
            indexed = False
            if self._ingestor is not None:
                try:
                    data = vault.resolve(args.path).read_bytes()
                    await self._ingestor.ingest(NOTES_PREFIX + str(written["path"]), data)
                    indexed = True
                except Exception:  # noqa: BLE001 - never turn a saved note into an error
                    indexed = False
            return {"status": "written", "indexed": indexed, **written}
        return {"tasks": await asyncio.to_thread(vault.open_tasks)}  # list_tasks

    async def _run(self, code: str) -> dict[str, Any]:
        try:
            run = await self._sandbox.run(code)
        except SandboxError as exc:
            return {"status": "error", "error": str(exc)}
        return {"status": "executed", **asdict(run)}

    async def execute(
        self,
        name: str,
        args: BaseModel,
        *,
        citation_offset: int,
        approved_program: str | None = None,
    ) -> ToolOutput:
        """Run a validated tool call. For run_skill, `approved_program` is the exact program
        the user approved, so a skill edited in between can never run unseen."""
        if isinstance(args, SearchKnowledgeArgs):
            citations = await self._retriever.search(args.query)
            for c in citations:
                c.n += citation_offset  # keep [n] numbers unique within the conversation turn
            found = [asdict(c) for c in citations]
            results = [
                {
                    "n": c["n"],
                    "source": c["source_path"],
                    "section": c["heading"],
                    "text": c["text"],
                }
                for c in found
            ]
            return ToolOutput({"results": results}, found)

        if name == "list_facts":
            facts = await self._facts.list()
            return ToolOutput({"facts": [{"id": f["id"], "fact": f["fact"]} for f in facts]}, [])

        if isinstance(args, RememberFactArgs):
            saved = await self._facts.remember(args.fact, args.category)
            return ToolOutput({"status": "saved", **saved.model_dump()}, [])

        if isinstance(args, ForgetFactArgs):
            deleted = await self._facts.forget(args.fact_id)
            return ToolOutput({"status": "deleted" if deleted else "not_found"}, [])

        if isinstance(args, RunCodeArgs):
            return ToolOutput(await self._run(args.code), [])

        if name == "list_skills":
            skills = [
                {"name": s.name, "description": s.description, "parameters": s.parameters}
                for s in self._skills.list()
            ]
            return ToolOutput({"skills": skills}, [])

        if isinstance(args, SaveSkillArgs):
            skill, created = self._skills.save(Skill(**args.model_dump()))
            return ToolOutput({"status": "saved" if created else "updated", "name": skill.name}, [])

        if isinstance(args, RunSkillArgs):
            try:
                program = approved_program or build_program(
                    self._skills.get(args.name), args.params
                )
            except SkillError as exc:
                return ToolOutput({"status": "error", "error": str(exc)}, [])
            result = await self._run(program)
            if result.get("exit_code") == 0:
                self._skills.record_run(args.name)
            return ToolOutput({"skill": args.name, **result}, [])

        if isinstance(args, DeleteSkillArgs):
            deleted = self._skills.delete(args.name)
            return ToolOutput({"status": "deleted" if deleted else "not_found"}, [])

        if isinstance(args, WeatherArgs):
            try:
                return ToolOutput(await get_weather(args.place, args.days), [])
            except (WebError, httpx.HTTPError) as exc:
                return ToolOutput({"status": "error", "error": str(exc) or type(exc).__name__}, [])

        if isinstance(args, WebSearchArgs):
            if self._settings is None:
                return ToolOutput({"status": "error", "error": "Web search is not configured."}, [])
            try:
                return ToolOutput(await web_search(args.query, self._settings), [])
            except WebError as exc:
                return ToolOutput({"status": "error", "error": str(exc)}, [])

        if name in PROJECT_TOOLS:
            if self._workspace is None:
                return ToolOutput(NO_PROJECTS, [])
            try:
                return ToolOutput(await self._projects(name, args), [])
            except (WorkspaceError, OSError) as exc:
                return ToolOutput({"status": "error", "error": str(exc)}, [])

        if name in ("list_notes", "read_note", "search_notes", "list_tasks", "write_note"):
            if self._vault is None:
                return ToolOutput(NO_VAULT, [])
            try:
                return ToolOutput(await self._notes(name, args), [])
            except (VaultError, OSError) as exc:
                return ToolOutput({"status": "error", "error": str(exc)}, [])

        return ToolOutput({"status": "error", "error": f"Unknown tool {name}"}, [])
