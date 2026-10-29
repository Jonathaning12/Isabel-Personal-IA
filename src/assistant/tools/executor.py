"""Execute an already-validated (and, if needed, already-approved) tool call."""

from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel

from assistant.memory.facts import FactMemory
from assistant.memory.retrieval import Retriever
from assistant.sandbox.base import SandboxRunner
from assistant.sandbox.docker_runner import SandboxError
from assistant.skills.store import Skill, SkillError, SkillStore, build_program
from assistant.tools.registry import (
    DeleteSkillArgs,
    ForgetFactArgs,
    RememberFactArgs,
    RunCodeArgs,
    RunSkillArgs,
    SaveSkillArgs,
    SearchKnowledgeArgs,
)


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
    ):
        self._retriever = retriever
        self._facts = facts
        self._sandbox = sandbox
        self._skills = skills

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

        return ToolOutput({"status": "error", "error": f"Unknown tool {name}"}, [])
