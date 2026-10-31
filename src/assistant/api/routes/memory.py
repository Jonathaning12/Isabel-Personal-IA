"""Memory endpoints: ingest documents, search, ask with citations, manage user facts."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from assistant.agent.rag import answer_question

router = APIRouter()

MAX_QUESTION_CHARS = 2000
MAX_FACT_CHARS = 500
MAX_MESSAGE_CHARS = 8000


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class FactRequest(BaseModel):
    fact: str = Field(min_length=1, max_length=MAX_FACT_CHARS)
    category: str = "other"


class LearnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


@router.post("/ingest")
async def ingest(request: Request, files: list[UploadFile]) -> dict:
    """Upload files from the CLI. The filename is used as the document's source path."""
    state = request.app.state
    max_bytes = state.settings.max_upload_mb * 1024 * 1024
    results = []
    for upload in files:
        data = await upload.read(max_bytes + 1)
        name = upload.filename or "unnamed"
        if len(data) > max_bytes:
            results.append({"source_path": name, "status": "skipped", "message": "File too large"})
            continue
        results.append(asdict(await state.ingestor.ingest(name, data)))
    return {"results": results}


@router.get("/documents")
async def list_documents(request: Request) -> dict:
    return {"documents": await request.app.state.store.list_documents()}


@router.delete("/documents")
async def delete_document(request: Request, source_path: str) -> dict:
    removed = await request.app.state.store.delete_document(source_path)
    if not removed:
        raise HTTPException(404, "Document not found")
    return {"source_path": source_path, "removed_chunks": removed}


@router.get("/memory/search")
async def search(request: Request, q: str, k: int = 5) -> dict:
    citations = await request.app.state.retriever.search(q[:MAX_QUESTION_CHARS], k=min(k, 20))
    return {"results": [asdict(c) for c in citations]}


@router.post("/ask")
async def ask(request: Request, body: AskRequest) -> dict:
    state = request.app.state
    result = await answer_question(
        body.question, retriever=state.retriever, facts=state.facts, chat=state.chat
    )
    return asdict(result)


@router.get("/memory/facts")
async def list_facts(request: Request) -> dict:
    return {"facts": await request.app.state.facts.list()}


@router.post("/memory/facts")
async def remember_fact(request: Request, body: FactRequest) -> dict:
    return (await request.app.state.facts.remember(body.fact, body.category)).model_dump()


@router.post("/memory/learn")
async def learn(request: Request, body: LearnRequest) -> dict:
    """Extract durable facts from free text (with Nemotron) and store them."""
    results = await request.app.state.facts.learn(body.text)
    return {"facts": [r.model_dump() for r in results]}


@router.get("/habits")
async def habits(request: Request) -> dict:
    """What Isabel learned by watching (today: the most played artists)."""
    top = request.app.state.habits.top_artists(limit=10)
    return {"artists": [{"name": name, "plays": plays} for name, plays in top]}


@router.delete("/habits")
async def forget_habits(request: Request) -> dict:
    request.app.state.habits.clear()
    return {"deleted": True}


@router.delete("/memory/facts/{fact_id}")
async def forget_fact(request: Request, fact_id: str) -> dict:
    if not await request.app.state.facts.forget(fact_id):
        raise HTTPException(404, "Fact not found")
    return {"id": fact_id, "deleted": True}
