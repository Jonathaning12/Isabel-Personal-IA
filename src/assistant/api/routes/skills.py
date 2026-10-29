"""Skills endpoints: list, inspect and delete the user's saved skills.

Saving and running skills happen through the agent (/chat), always with approval.
"""

from fastapi import APIRouter, HTTPException, Request

from assistant.skills.store import SkillError

router = APIRouter()


@router.get("/skills")
async def list_skills(request: Request) -> dict:
    return {"skills": [s.model_dump() for s in request.app.state.skills.list()]}


@router.get("/skills/{name}")
async def get_skill(request: Request, name: str) -> dict:
    try:
        return request.app.state.skills.get(name).model_dump()
    except SkillError:
        raise HTTPException(404, "Skill not found") from None


@router.delete("/skills/{name}")
async def delete_skill(request: Request, name: str) -> dict:
    if not request.app.state.skills.delete(name):
        raise HTTPException(404, "Skill not found")
    return {"name": name, "deleted": True}
