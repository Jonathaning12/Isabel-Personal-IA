"""Health check: is the app up, can it reach Nebius and Qdrant?

Never returns the API key, only the configured model IDs.
"""

import httpx
from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/health")
async def health(request: Request, response: Response) -> dict[str, object]:
    settings = request.app.state.settings

    nebius = "ok"
    try:
        await request.app.state.openai.models.list(timeout=10)
    except Exception as exc:  # report any failure as a status, never crash the check
        nebius = f"error: {type(exc).__name__}"

    qdrant = "ok"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            (await client.get(f"{settings.qdrant_url}/readyz")).raise_for_status()
    except Exception as exc:
        qdrant = f"error: {type(exc).__name__}"

    if nebius != "ok":
        response.status_code = 503
    return {
        "status": "ok" if nebius == "ok" and qdrant == "ok" else "degraded",
        "nebius": nebius,
        "qdrant": qdrant,
        "models": {"llm": settings.llm_model, "embeddings": settings.embed_model},
    }
