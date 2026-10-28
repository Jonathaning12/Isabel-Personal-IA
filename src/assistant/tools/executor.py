"""Execute an already-validated (and, if needed, already-approved) tool call."""

from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel

from assistant.memory.facts import FactMemory
from assistant.memory.retrieval import Retriever
from assistant.sandbox.base import SandboxRunner
from assistant.sandbox.docker_runner import SandboxError
from assistant.tools.registry import (
    ForgetFactArgs,
    RememberFactArgs,
    RunCodeArgs,
    SearchKnowledgeArgs,
)


@dataclass
class ToolOutput:
    result: dict[str, Any]
    new_citations: list[dict[str, Any]]


class ToolExecutor:
    def __init__(self, retriever: Retriever, facts: FactMemory, sandbox: SandboxRunner):
        self._retriever = retriever
        self._facts = facts
        self._sandbox = sandbox

    async def execute(self, name: str, args: BaseModel, *, citation_offset: int) -> ToolOutput:
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
            try:
                run = await self._sandbox.run(args.code)
            except SandboxError as exc:
                return ToolOutput({"status": "error", "error": str(exc)}, [])
            return ToolOutput({"status": "executed", **asdict(run)}, [])

        return ToolOutput({"status": "error", "error": f"Unknown tool {name}"}, [])
