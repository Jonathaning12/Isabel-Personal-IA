"""Tools the agent can use, with their argument schemas and side-effect flag.

How tool calling works: Nemotron never executes anything. It replies with a JSON
"I want to call tool X with these arguments". Our code validates the arguments
against a Pydantic schema and decides whether to run it. Tools with side_effect=True
(they change memory or run code) ALWAYS need the user's explicit approval first.
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="What to search for")


class ListFactsArgs(BaseModel):
    pass


class RememberFactArgs(BaseModel):
    fact: str = Field(
        min_length=1,
        max_length=500,
        description="Durable fact about the user, as a short third-person sentence in Spanish",
    )
    category: Literal["preference", "personal", "work", "goal", "other"] = "other"


class ForgetFactArgs(BaseModel):
    fact_id: str = Field(min_length=1, max_length=64, description="Exact id from list_facts")


class RunCodeArgs(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=20_000,
        description="Complete Python 3 program. Print the results with print().",
    )
    explanation: str = Field(
        default="",
        max_length=500,
        description="One short sentence in Spanish explaining what the code does",
    )


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    side_effect: bool


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "search_knowledge",
            "Search the user's personal notes and documents. Use it when the provided "
            "context is missing or not enough to answer.",
            SearchKnowledgeArgs,
            side_effect=False,
        ),
        Tool(
            "list_facts",
            "List the facts stored about the user, with their ids.",
            ListFactsArgs,
            side_effect=False,
        ),
        Tool(
            "remember_fact",
            "Store a durable fact about the user in long-term memory. Use it when the user "
            "asks you to remember something or states a lasting preference.",
            RememberFactArgs,
            side_effect=True,
        ),
        Tool(
            "forget_fact",
            "Delete a stored fact about the user. Call list_facts first to get the id.",
            ForgetFactArgs,
            side_effect=True,
        ),
        Tool(
            "run_code_in_sandbox",
            "Run a Python 3 program in an isolated sandbox: no internet, no access to the "
            "user's files, 30 s limit; numpy and pandas are available. Use it for calculations, "
            "data processing, or when the user asks to run code.",
            RunCodeArgs,
            side_effect=True,
        ),
    )
}


def openai_tool_specs() -> list[dict[str, Any]]:
    """Tool definitions in the OpenAI `tools` format that Nebius accepts."""
    specs = []
    for tool in TOOLS.values():
        schema = tool.args_model.model_json_schema()
        schema.pop("title", None)
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema,
                },
            }
        )
    return specs
