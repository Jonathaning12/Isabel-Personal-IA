"""The agent's state: what LangGraph stores (and checkpoints) for each conversation thread.

`messages` uses an "add" reducer: nodes return new messages and LangGraph appends them,
like a Redux reducer. The other fields are overwritten by each node that returns them.
"""

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    messages: Annotated[list[dict[str, Any]], operator.add]  # OpenAI-format conversation
    context: list[dict[str, Any]]  # citations available in the current turn
    facts: list[str]  # user facts relevant to the current turn
    actions: list[dict[str, Any]]  # tools executed (or rejected) in the current turn
    iterations: int  # agent ⇄ tools round trips in the current turn (loop guard)
    notes_unavailable: bool  # note search failed this turn (e.g. Nebius embedding timeout)
    previous_sources: list[str]  # sources cited in the previous answer ("where did you get that?")
    now: str  # the user's local date and time for this turn, sent by the client
    project: str | None  # the project folder selected in the app ("esta carpeta")
    user_name: str | None  # the name the user set in the app, if any
    episodes: list[str]  # summaries of related past conversations, with their date
