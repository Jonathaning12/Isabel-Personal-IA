"""The agent as a LangGraph state machine.

    START → load_context → agent ──(tool calls?)──→ tools ──→ agent → … → END
                                                        └──(all rejected)──→ END
                                 └──(no tool calls)──→ END

- load_context: semantic search in the user's notes + relevant user facts (no LLM call).
- agent: Nemotron reads the conversation and either answers or requests tools.
- tools: validates each tool call. Side-effect tools PAUSE the graph with `interrupt()`
  until the user approves or rejects; only approved calls run. All approvals are asked
  BEFORE anything runs, so resuming never executes an action twice. If the user rejects
  every action, the turn ends with a fixed reply (no LLM call, so no workaround).

State is checkpointed per thread_id (SQLite), so conversations survive restarts.
"""

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from assistant.agent.prompts import (
    AGENT_SYSTEM,
    ALL_REJECTED_ANSWER,
    FACTS_BLOCK,
    NO_NOTES_CONTEXT,
    NOTES_UNAVAILABLE,
    PREVIOUS_SOURCES_BLOCK,
    SKILLS_BLOCK,
)
from assistant.agent.rag import format_context, normalize_citations
from assistant.agent.state import AgentState
from assistant.config import Settings
from assistant.guardrails.audit import AuditLog
from assistant.memory.facts import FactMemory, SupportsComplete
from assistant.memory.retrieval import Citation, Retriever
from assistant.sandbox.base import SandboxRunner
from assistant.skills.store import Skill, SkillStore, build_program
from assistant.tools.executor import ToolExecutor
from assistant.tools.registry import TOOLS, openai_tool_specs

APPROVE = "approve"
logger = logging.getLogger("assistant.agent")


@dataclass
class AgentDeps:
    chat: SupportsComplete
    retriever: Retriever
    facts: FactMemory
    sandbox: SandboxRunner
    audit: AuditLog
    settings: Settings
    skills: SkillStore


def build_system_prompt(
    facts: list[str],
    context: list[dict[str, Any]],
    *,
    previous_sources: list[str] | None = None,
    notes_unavailable: bool = False,
    skills: list[Skill] | None = None,
) -> str:
    facts_block = FACTS_BLOCK.format(facts="\n".join(f"- {f}" for f in facts)) if facts else ""
    sources_block = (
        PREVIOUS_SOURCES_BLOCK.format(sources="\n".join(f"- {s}" for s in previous_sources))
        if previous_sources
        else ""
    )
    skills_block = (
        SKILLS_BLOCK.format(
            skills="\n".join(
                f"- {s.name}({', '.join(s.parameters)}): {s.description}" for s in skills
            )
        )
        if skills
        else ""
    )
    citations = [Citation(**c) for c in context]
    if citations:
        context_block = format_context(citations)
    else:
        context_block = NOTES_UNAVAILABLE if notes_unavailable else NO_NOTES_CONTEXT
    return AGENT_SYSTEM.format(
        facts_block=facts_block,
        skills_block=skills_block,
        previous_sources_block=sources_block,
        context_block=context_block,
    )


def cited_sources(answer: str, context: list[dict[str, Any]]) -> list[str]:
    """Human-readable list of the sources an answer cited, e.g. '[1] notes/gym.txt › Lunes'."""
    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    sources = []
    for c in context:
        if c["n"] in numbers:
            section = f" › {c['heading']}" if c.get("heading") else ""
            sources.append(f"[{c['n']}] {c['source_path']}{section}")
    return sources


def payload_fingerprint(payload: dict[str, Any]) -> str:
    """SHA-256 of an approval request. An approval is only valid for this exact payload."""
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode()).hexdigest()


def classify_decision(decision: Any, payload: dict[str, Any]) -> str:
    """ "approve" only for {"decision": "approve", "fingerprint": <this payload's fingerprint>}.

    On resume LangGraph re-runs the node and rebuilds the payload. If anything changed
    since the user saw it (e.g. a skill was edited), the fingerprint no longer matches:
    the action is "stale" and does not run. Anything else is "reject".
    """
    if isinstance(decision, dict) and decision.get("decision") == APPROVE:
        if decision.get("fingerprint") == payload_fingerprint(payload):
            return APPROVE
        return "stale"
    return "reject"


def _summary(result: dict[str, Any]) -> str:
    if "exit_code" in result:
        return f"exit_code={result['exit_code']} timed_out={result['timed_out']}"
    return str(result.get("status", "ok"))


def build_graph(deps: AgentDeps, checkpointer: Any) -> Any:
    executor = ToolExecutor(deps.retriever, deps.facts, deps.sandbox, deps.skills)
    tool_specs = openai_tool_specs()

    async def load_context(state: AgentState) -> dict[str, Any]:
        # Remember which sources the previous answer cited, before this turn's search
        # replaces the context ("where did you get that?").
        previous = [m for m in state["messages"][:-1] if m["role"] == "assistant"]
        previous_sources = (
            cited_sources(previous[-1]["content"], state.get("context", [])) if previous else []
        )

        question = state["messages"][-1]["content"]
        try:
            vector = await deps.retriever.embed_query(question)
            citations = [asdict(c) for c in await deps.retriever.search_by_vector(vector)]
            facts = await deps.facts.relevant(vector)
            unavailable = False
        except Exception as exc:  # degrade gracefully: answer without notes
            logger.warning("load_context_failed error=%s", type(exc).__name__)
            citations, facts, unavailable = [], [], True
        return {
            "context": citations,
            "facts": facts,
            "actions": [],
            "iterations": 0,
            "notes_unavailable": unavailable,
            "previous_sources": previous_sources,
        }

    async def agent(state: AgentState) -> dict[str, Any]:
        # Loop guard: after too many round trips, force a final answer without tools.
        allow_tools = state["iterations"] < deps.settings.max_agent_iterations
        system = build_system_prompt(
            state["facts"],
            state["context"],
            previous_sources=state.get("previous_sources"),
            notes_unavailable=state.get("notes_unavailable", False),
            skills=deps.skills.list(),
        )
        reply = await deps.chat.complete(
            [{"role": "system", "content": system}, *state["messages"]],
            tools=tool_specs if allow_tools else None,
            thinking=True,
        )
        message: dict[str, Any] = {
            "role": "assistant",
            "content": normalize_citations(reply.content or ""),
        }
        if allow_tools and reply.tool_calls:
            message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in reply.tool_calls
            ]
        return {"messages": [message], "iterations": state["iterations"] + 1}

    def route_after_agent(state: AgentState) -> str:
        return "tools" if state["messages"][-1].get("tool_calls") else END

    async def tools(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        thread_id = config["configurable"]["thread_id"]
        calls = state["messages"][-1]["tool_calls"]

        # 1. Validate every call against its schema. For run_skill, resolve the exact
        #    program now: it is what the user will see and what will run.
        parsed = []
        programs: dict[str, str] = {}
        for call in calls:
            name = call["function"]["name"]
            tool = TOOLS.get(name)
            try:
                if tool is None:
                    raise ValueError(f"Unknown tool: {name}")
                args = tool.args_model.model_validate(
                    json.loads(call["function"]["arguments"] or "{}")
                )
                if name == "run_skill":
                    skill = deps.skills.get(args.name)
                    programs[call["id"]] = build_program(skill, args.params)
                parsed.append((call, tool, args, None))
            except (ValueError, ValidationError) as exc:  # SkillError is a ValueError
                parsed.append((call, tool, None, f"Invalid tool call: {exc}"))

        # 2. Ask for ALL approvals first. Nothing has run yet, so when LangGraph re-runs
        #    this node on resume, no action can be executed twice.
        decisions: dict[str, str] = {}
        for call, tool, args, error in parsed:
            if error is None and tool.side_effect:
                payload: dict[str, Any] = {
                    "tool_call_id": call["id"],
                    "tool": tool.name,
                    "args": args.model_dump(),
                }
                if tool.name in ("run_code_in_sandbox", "run_skill"):
                    payload["limits"] = deps.sandbox.limits()
                if tool.name == "run_skill":
                    payload["program"] = programs[call["id"]]
                    payload["description"] = deps.skills.get(args.name).description
                decisions[call["id"]] = classify_decision(interrupt(payload), payload)

        # 3. Execute: read-only tools directly, side-effect tools only if approved.
        messages, actions = [], list(state["actions"])
        new_citations: list[dict[str, Any]] = []
        offset = len(state["context"])
        for call, tool, args, error in parsed:
            name = call["function"]["name"]
            decision = None
            if error is not None:
                result: dict[str, Any] = {"status": "error", "error": error}
            elif tool.side_effect and decisions.get(call["id"]) == "stale":
                decision = "stale"
                result = {
                    "status": "not_run",
                    "message": "The action changed after the user saw it, so it was not run. "
                    "Tell the user and request it again.",
                }
            elif tool.side_effect and decisions.get(call["id"]) != APPROVE:
                decision = "reject"
                result = {
                    "status": "rejected",
                    "message": "The user rejected this action. Do not retry it.",
                }
            else:
                decision = APPROVE if tool.side_effect else None
                try:
                    output = await executor.execute(
                        name,
                        args,
                        citation_offset=offset + len(new_citations),
                        approved_program=programs.get(call["id"]),
                    )
                    result = output.result
                    new_citations += output.new_citations
                except Exception as exc:  # e.g. Nebius timeout: report it to the model
                    logger.warning("tool_failed tool=%s error=%s", name, type(exc).__name__)
                    result = {
                        "status": "error",
                        "error": f"The tool failed ({type(exc).__name__}). Tell the user to "
                        "try again in a moment.",
                    }
            if decision is not None:
                deps.audit.record(
                    thread_id=thread_id,
                    tool=name,
                    args=args.model_dump() if args else {},
                    decision=decision,
                    summary=_summary(result),
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            actions.append(
                {
                    "tool": name,
                    "args": args.model_dump() if args else {},
                    "decision": decision,
                    "result": result,
                }
            )
        # Every requested action was rejected → end the turn here, enforced in code.
        if all(a["decision"] == "reject" for a in actions[len(state["actions"]) :]):
            messages.append({"role": "assistant", "content": ALL_REJECTED_ANSWER})
        return {
            "messages": messages,
            "actions": actions,
            "context": state["context"] + new_citations,
        }

    def route_after_tools(state: AgentState) -> str:
        return END if state["messages"][-1]["role"] == "assistant" else "agent"

    graph = StateGraph(AgentState)
    graph.add_node("load_context", load_context)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "agent")
    graph.add_conditional_edges("agent", route_after_agent, ["tools", END])
    graph.add_conditional_edges("tools", route_after_tools, ["agent", END])
    return graph.compile(checkpointer=checkpointer)
