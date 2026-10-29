"""Chat with the agent.

POST /chat                       → send a message; returns the answer, or the action that
                                   needs approval (status "confirm_required").
POST /chat/{thread_id}/confirm   → approve or reject the pending action, then continue.
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel, Field

from assistant.agent.graph import payload_fingerprint

router = APIRouter()

MAX_MESSAGE_CHARS = 8000


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    thread_id: str | None = Field(default=None, max_length=64)


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
        return {**base, "status": "confirm_required", "pending": result["__interrupt__"][0].value}
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
    result = await request.app.state.graph.ainvoke(
        {"messages": [{"role": "user", "content": body.message}]}, _config(thread_id)
    )
    return _response(thread_id, result)


@router.post("/chat/{thread_id}/confirm")
async def confirm(request: Request, thread_id: str, body: ConfirmRequest) -> dict[str, Any]:
    pending = await _pending(request, thread_id)
    if pending is None:
        raise HTTPException(409, "There is no action waiting for approval")
    # Bind the decision to the exact action the user was shown.
    resume = {"decision": body.decision, "fingerprint": payload_fingerprint(pending)}
    result = await request.app.state.graph.ainvoke(Command(resume=resume), _config(thread_id))
    return _response(thread_id, result)
