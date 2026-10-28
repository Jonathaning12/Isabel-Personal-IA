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

import json
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
)
from assistant.agent.rag import format_context, normalize_citations
from assistant.agent.state import AgentState
from assistant.config import Settings
from assistant.guardrails.audit import AuditLog
from assistant.memory.facts import FactMemory, SupportsComplete
from assistant.memory.retrieval import Citation, Retriever
from assistant.sandbox.base import SandboxRunner
from assistant.tools.executor import ToolExecutor
from assistant.tools.registry import TOOLS, openai_tool_specs

APPROVE = "approve"


@dataclass
class AgentDeps:
    chat: SupportsComplete
    retriever: Retriever
    facts: FactMemory
    sandbox: SandboxRunner
    audit: AuditLog
    settings: Settings


def build_system_prompt(facts: list[str], context: list[dict[str, Any]]) -> str:
    facts_block = FACTS_BLOCK.format(facts="\n".join(f"- {f}" for f in facts)) if facts else ""
    citations = [Citation(**c) for c in context]
    context_block = format_context(citations) if citations else NO_NOTES_CONTEXT
    return AGENT_SYSTEM.format(facts_block=facts_block, context_block=context_block)


def _summary(result: dict[str, Any]) -> str:
    if "exit_code" in result:
        return f"exit_code={result['exit_code']} timed_out={result['timed_out']}"
    return str(result.get("status", "ok"))


def build_graph(deps: AgentDeps, checkpointer: Any) -> Any:
    executor = ToolExecutor(deps.retriever, deps.facts, deps.sandbox)
    tool_specs = openai_tool_specs()

    async def load_context(state: AgentState) -> dict[str, Any]:
        question = state["messages"][-1]["content"]
        vector = await deps.retriever.embed_query(question)
        citations = await deps.retriever.search_by_vector(vector)
        facts = await deps.facts.relevant(vector)
        return {
            "context": [asdict(c) for c in citations],
            "facts": facts,
            "actions": [],
            "iterations": 0,
        }

    async def agent(state: AgentState) -> dict[str, Any]:
        # Loop guard: after too many round trips, force a final answer without tools.
        allow_tools = state["iterations"] < deps.settings.max_agent_iterations
        system = build_system_prompt(state["facts"], state["context"])
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

        # 1. Validate every call against its schema.
        parsed = []
        for call in calls:
            name = call["function"]["name"]
            tool = TOOLS.get(name)
            try:
                if tool is None:
                    raise ValueError(f"Unknown tool: {name}")
                args = tool.args_model.model_validate(
                    json.loads(call["function"]["arguments"] or "{}")
                )
                parsed.append((call, tool, args, None))
            except (ValueError, ValidationError) as exc:
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
                if tool.name == "run_code_in_sandbox":
                    payload["limits"] = deps.sandbox.limits()
                decisions[call["id"]] = interrupt(payload)

        # 3. Execute: read-only tools directly, side-effect tools only if approved.
        messages, actions = [], list(state["actions"])
        new_citations: list[dict[str, Any]] = []
        offset = len(state["context"])
        for call, tool, args, error in parsed:
            name = call["function"]["name"]
            decision = None
            if error is not None:
                result: dict[str, Any] = {"status": "error", "error": error}
            elif tool.side_effect and decisions.get(call["id"]) != APPROVE:
                decision = "reject"
                result = {
                    "status": "rejected",
                    "message": "The user rejected this action. Do not retry it.",
                }
            else:
                decision = APPROVE if tool.side_effect else None
                output = await executor.execute(
                    name, args, citation_offset=offset + len(new_citations)
                )
                result = output.result
                new_citations += output.new_citations
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
