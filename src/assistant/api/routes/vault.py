"""Obsidian vault endpoints.

GET  /vault       → is a vault configured, its name, how many notes.
POST /vault/sync  → index every note into the semantic search (idempotent: unchanged notes
                    cost nothing) and drop notes that were deleted from the vault.
Reading and writing notes happens through the agent's tools (writes need approval).
"""

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from assistant.tools.executor import NOTES_PREFIX

router = APIRouter()


@router.get("/vault")
async def vault_info(request: Request) -> dict:
    vault = request.app.state.vault
    if vault is None:
        return {"configured": False}
    return {
        "configured": True,
        "name": request.app.state.settings.obsidian_vault_name,
        "notes": len(await asyncio.to_thread(vault.all_paths)),
    }


@router.post("/vault/sync")
async def vault_sync(request: Request) -> dict:
    state = request.app.state
    vault = state.vault
    if vault is None:
        raise HTTPException(404, "No Obsidian vault configured")
    results = []
    present = set()
    # Every note (uncapped), file reads off the event loop.
    for path in await asyncio.to_thread(vault.all_paths):
        source = NOTES_PREFIX + path
        present.add(source)
        data = await asyncio.to_thread(vault.resolve(path).read_bytes)
        results.append(asdict(await state.ingestor.ingest(source, data)))
    removed = 0
    for doc in await state.store.list_documents():
        path = doc["source_path"]
        if path.startswith(NOTES_PREFIX) and path not in present:
            await state.store.delete_document(path)
            removed += 1
    return {"results": results, "removed": removed}
