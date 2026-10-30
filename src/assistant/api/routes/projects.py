"""Projects folder endpoint for the desktop app's "Proyectos" tab.

GET /projects → is a projects folder configured, its name, its folders and git repos.
Git actions themselves go through the agent's tools (commit, push and folder creation
always need the user's approval).
"""

import asyncio

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/projects")
async def list_projects(request: Request) -> dict:
    workspace = request.app.state.workspace
    if workspace is None:
        return {"configured": False}
    found = await asyncio.to_thread(workspace.list_projects)
    return {
        "configured": True,
        "name": request.app.state.settings.projects_name,
        "github": bool(request.app.state.settings.github_token.get_secret_value()),
        # Where this folder is on the user's computer, so the app can open files there.
        "host_root": request.app.state.settings.projects_host_path,
        **found,
    }
