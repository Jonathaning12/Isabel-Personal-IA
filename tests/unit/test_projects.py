"""Unit tests for the projects folder: path safety, folders and git (real git, temp repos)."""

import shutil
import subprocess

import pytest

from assistant.workspace.projects import Workspace, WorkspaceError

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def run(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "Documentos"
    repo = root / "Algoria"
    repo.mkdir(parents=True)
    (root / "Fotos").mkdir()
    remote = tmp_path / "remote.git"
    run("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    run("init", "-b", "main", cwd=repo)
    run("config", "user.email", "test@example.com", cwd=repo)
    run("config", "user.name", "Test", cwd=repo)
    (repo / "app.py").write_text("print('hola')\n", encoding="utf-8")
    run("add", "-A", cwd=repo)
    run("commit", "-m", "first", cwd=repo)
    run("remote", "add", "origin", str(remote), cwd=repo)
    run("push", "-u", "origin", "main", cwd=repo)
    return Workspace(root, autocrlf="true")


@pytest.mark.parametrize("path", ["../x", "/etc", "C:/Windows", ".git", "Algoria/../../x", ""])
def test_paths_outside_the_projects_folder_are_rejected(projects, path):
    with pytest.raises(WorkspaceError):
        projects.resolve(path)


def test_list_projects_and_create_folder(projects):
    found = projects.list_projects()
    assert found["repos"] == ["Algoria"]
    assert set(found["folders"]) == {"Algoria", "Fotos"}

    assert projects.create_folder("Pruebas de IA")["status"] == "created"
    assert (projects.root / "Pruebas de IA").is_dir()
    for bad in ("Pruebas de IA", "mal:nombre", "con?pregunta"):
        with pytest.raises(WorkspaceError):
            projects.create_folder(bad)


async def test_status_commit_and_push(projects):
    repo = projects.root / "Algoria"
    clean = await projects.status("Algoria", fetch=False)
    assert clean["uncommitted_changes"] == [] and clean["ahead"] == 0

    (repo / "nuevo.py").write_text("x = 1\n", encoding="utf-8")
    dirty = await projects.status("Algoria", fetch=False)
    assert dirty["uncommitted_changes"] == ["?? nuevo.py"]
    assert "nuevo.py" in (await projects.diff("Algoria"))["untracked_files"]

    committed = await projects.commit("Algoria", "feat: add nuevo")
    assert "feat: add nuevo" in committed["commit"]
    ahead = await projects.status("Algoria", fetch=False)
    assert ahead["ahead"] == 1 and "feat: add nuevo" in ahead["unpushed_commits"][0]

    assert (await projects.push("Algoria"))["status"] == "pushed"
    assert (await projects.status("Algoria", fetch=True))["ahead"] == 0


async def test_not_a_repository(projects):
    with pytest.raises(WorkspaceError):
        await projects.status("Fotos")


async def test_push_to_github_without_token_explains_what_is_missing(projects):
    run(
        "remote",
        "set-url",
        "origin",
        "https://github.com/someone/repo.git",
        cwd=projects.root / "Algoria",
    )
    with pytest.raises(WorkspaceError, match="GITHUB_TOKEN"):
        await projects.push("Algoria")
