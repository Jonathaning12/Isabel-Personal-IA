"""Answer a question from the user's documents with citations (RAG).

1. Retrieve the closest chunks (Retriever).
2. Put them in the prompt as numbered <context> blocks, plus relevant user facts.
3. Nemotron answers in Spanish, citing [n]. No context → fixed answer, no LLM call.

Phase 3 will wrap this in the LangGraph agent; for now it is a single function.
"""

import re
from dataclasses import dataclass, field
from html import escape

from assistant.agent.prompts import ANSWER_SYSTEM, FACTS_BLOCK, NO_CONTEXT_ANSWER
from assistant.memory.facts import FactMemory, SupportsComplete
from assistant.memory.retrieval import Citation, Retriever

FULLWIDTH_CITATION = re.compile(r"【\s*(\d+)\s*(?:†[^】]*)?】")
FULLWIDTH_OTHER = re.compile(r"\s*【[^】]*】")


def normalize_citations(answer: str) -> str:
    """Nemotron sometimes cites as 【1】 → [1]; non-numeric 【notes】 are dropped."""
    return FULLWIDTH_OTHER.sub("", FULLWIDTH_CITATION.sub(r"[\1]", answer))


@dataclass
class Answer:
    answer: str
    citations: list[Citation]
    facts_used: list[str] = field(default_factory=list)


def format_context(citations: list[Citation]) -> str:
    blocks = []
    for c in citations:
        attrs = f'n="{c.n}" source="{escape(c.source_path)}"'
        if c.title:
            attrs += f' title="{escape(c.title)}"'
        if c.heading:
            attrs += f' section="{escape(c.heading)}"'
        if c.suspicious:
            attrs += ' suspicious="true"'
        blocks.append(f"<context {attrs}>\n{c.text}\n</context>")
    return "\n\n".join(blocks)


def build_messages(question: str, citations: list[Citation], facts: list[str]) -> list[dict]:
    facts_block = FACTS_BLOCK.format(facts="\n".join(f"- {f}" for f in facts)) if facts else ""
    return [
        {"role": "system", "content": ANSWER_SYSTEM.format(facts_block=facts_block).strip()},
        {"role": "user", "content": f"{format_context(citations)}\n\nQuestion: {question}"},
    ]


async def answer_question(
    question: str,
    *,
    retriever: Retriever,
    facts: FactMemory,
    chat: SupportsComplete,
) -> Answer:
    vector = await retriever.embed_query(question)
    citations = await retriever.search_by_vector(vector)
    if not citations:
        return Answer(answer=NO_CONTEXT_ANSWER, citations=[])

    user_facts = await facts.relevant(vector)
    response = await chat.complete(build_messages(question, citations, user_facts), thinking=True)
    answer = normalize_citations(response.content or "")
    return Answer(answer=answer, citations=citations, facts_used=user_facts)
