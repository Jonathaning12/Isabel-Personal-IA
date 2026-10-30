"""Chat with the agent.

POST /chat                       → send a message; returns the answer, or the action that
                                   needs approval (status "confirm_required").
POST /chat/{thread_id}/confirm   → approve or reject the pending action, then continue.
"""

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel, Field

from assistant.agent.clock import describe_now
from assistant.agent.graph import CLIENT_ACTION, payload_fingerprint

router = APIRouter()

MAX_MESSAGE_CHARS = 8000


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    thread_id: str | None = Field(default=None, max_length=64)
    # The client's clock: ISO 8601 with UTC offset, and its IANA time zone name.
    local_time: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_+\-/]+$")
    # The project folder selected in the app (relative to the projects folder).
    project: str | None = Field(default=None, max_length=200, pattern=r"^[^\"\n\r]+$")


class ConfirmRequest(BaseModel):
    decision: Literal["approve", "reject"]


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _response(thread_id: str, result: dict[str, Any]) -> dict[str, Any]:
    base = {
        "thread_id": thread_id,
        "actions": result.get("actions", []),
        "citations": result.get("context", []),
    }
    if result.get("__interrupt__"):
        pending = result["__interrupt__"][0].value
        status = "client_action" if pending.get("kind") == CLIENT_ACTION else "confirm_required"
        return {**base, "status": status, "pending": pending}
    return {**base, "status": "done", "answer": result["messages"][-1]["content"]}


async def _pending(request: Request, thread_id: str) -> dict[str, Any] | None:
    """The approval request currently waiting in this thread (what the user was shown)."""
    state = await request.app.state.graph.aget_state(_config(thread_id))
    interrupts = [i for task in state.tasks for i in task.interrupts]
    return interrupts[0].value if interrupts else None


@router.post("/chat")
async def chat(request: Request, body: ChatRequest) -> dict[str, Any]:
    thread_id = body.thread_id or uuid.uuid4().hex
    if await _pending(request, thread_id) is not None:
        raise HTTPException(409, "There is an action waiting for approval in this conversation")
    turn = {
        "messages": [{"role": "user", "content": body.message}],
        "now": describe_now(body.local_time, body.timezone),
        "project": body.project,
    }
    result = await request.app.state.graph.ainvoke(turn, _config(thread_id))
    return _response(thread_id, result)


@router.post("/chat/{thread_id}/confirm")
async def confirm(request: Request, thread_id: str, body: ConfirmRequest) -> dict[str, Any]:
    pending = await _pending(request, thread_id)
    if pending is None or pending.get("kind") == CLIENT_ACTION:
        raise HTTPException(409, "There is no action waiting for approval")
    # Bind the decision to the exact action the user was shown.
    resume = {"decision": body.decision, "fingerprint": payload_fingerprint(pending)}
    result = await request.app.state.graph.ainvoke(Command(resume=resume), _config(thread_id))
    return _response(thread_id, result)


@router.get("/chat/{thread_id}/pending-action")
async def pending_action(request: Request, thread_id: str) -> dict[str, Any]:
    """The computer action currently waiting for the desktop app (it only exists after any
    required approval). The app's main process checks it before running risky actions."""
    pending = await _pending(request, thread_id)
    if pending is None or pending.get("kind") != CLIENT_ACTION:
        raise HTTPException(404, "No computer action is waiting")
    return pending


class ClientResultRequest(BaseModel):
    tool_call_id: str = Field(min_length=1, max_length=100)
    result: dict[str, Any]


MAX_CLIENT_RESULT_CHARS = 8000


@router.post("/chat/{thread_id}/client-result")
async def client_result(
    request: Request, thread_id: str, body: ClientResultRequest
) -> dict[str, Any]:
    """The desktop app ran an action on the user's computer (e.g. Spotify) and reports back.
    Only answers a pending client_action, never an approval."""
    pending = await _pending(request, thread_id)
    if pending is None or pending.get("kind") != CLIENT_ACTION:
        raise HTTPException(409, "There is no computer action waiting for a result")
    if pending.get("tool_call_id") != body.tool_call_id:
        raise HTTPException(409, "This result belongs to another action")
    if len(json.dumps(body.result, ensure_ascii=False)) > MAX_CLIENT_RESULT_CHARS:
        raise HTTPException(413, "Result too large")
    resume = {"tool_call_id": body.tool_call_id, "client_result": body.result}
    result = await request.app.state.graph.ainvoke(Command(resume=resume), _config(thread_id))
    return _response(thread_id, result)
