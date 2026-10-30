"""The user's projects folder (e.g. Documents): folders and git repositories.

docker-compose mounts the host folder PROJECTS_HOST at /projects. Every path the agent
gives is relative to that root and is checked before use (no absolute paths, no `..`,
no hidden folders, and the real path must stay inside the root).

Read-only operations (list projects, git status, git diff) run freely. Creating folders,
committing and pushing are side effects: the agent's tools pause for the user's approval
first (see tools/registry.py).

Git runs inside the API container, so a few settings make it behave like the user's
Windows git on the same files: core.autocrlf (line endings), core.filemode=false (Windows
bind mounts report every file as executable) and safe.directory (files owned by another
user id). Pushing to GitHub uses GITHUB_TOKEN from .env through a credential helper; the
token is never written to disk or into a command line.
"""

import asyncio
import os
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

GIT_TIMEOUT_S = 30
PUSH_TIMEOUT_S = 90
MAX_DIFF_CHARS = 12_000
MAX_DEPTH = 3
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target"}
INVALID_NAME = re.compile(r'[<>:"|?*\x00-\x1f]')
# Credential helper that answers with the token from the environment (never on disk).
TOKEN_HELPER = '!f() { echo username=x-access-token; echo "password=$GITHUB_TOKEN"; }; f'


FIND_DEPTH = 6
FIND_MAX_SCANNED = 60_000
FIND_MAX_RESULTS = 30


def _plain(text: str) -> str:
    """Lowercase, no accents: "Factura Octubre" matches factura_octubre.pdf."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    without_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", without_accents)


class WorkspaceError(ValueError):
    """Invalid path, not a repository, or a git command that failed."""


class Workspace:
    def __init__(self, root: Path, *, autocrlf: str = "true", github_token: str = ""):
        self.root = root
        self._autocrlf = autocrlf
        self._token = github_token

    # ---- paths --------------------------------------------------------------------------

    def resolve(self, relative: str, *, allow_root: bool = False) -> Path:
        raw = relative.strip().replace("\\", "/")
        if raw.startswith("/"):  # check before trimming: "/etc" must not become "etc"
            raise WorkspaceError(f"Use a path relative to the projects folder: {relative}")
        cleaned = raw.strip("/")
        if not cleaned:
            if allow_root:
                return self.root.resolve()
            raise WorkspaceError("Give a folder relative to the projects folder, e.g. 'Algoria'")
        rel = PurePosixPath(cleaned)
        if rel.is_absolute() or re.match(r"^[A-Za-z]:", cleaned):
            raise WorkspaceError(f"Use a path relative to the projects folder: {relative}")
        if any(part in ("..", ".") or part.startswith(".") for part in rel.parts):
            raise WorkspaceError(f"Hidden folders and '..' are not allowed: {relative}")
        root = self.root.resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            raise WorkspaceError(f"Path outside the projects folder: {relative}")
        return path

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix() or "."

    def repo(self, relative: str) -> Path:
        path = self.resolve(relative)
        if not (path / ".git").exists():
            raise WorkspaceError(f"Not a git repository: {relative}")
        return path

    # ---- folders ------------------------------------------------------------------------

    def list_projects(self) -> dict[str, list[str]]:
        """Top-level folders, and git repositories up to MAX_DEPTH levels deep."""
        root = self.root.resolve()
        folders = sorted(
            p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")
        )
        repos: list[str] = []

        def walk(folder: Path, depth: int) -> None:
            if (folder / ".git").exists():
                repos.append(self.relative(folder))
                return
            if depth >= MAX_DEPTH:
                return
            try:
                children = sorted(folder.iterdir())
            except OSError:
                return
            for child in children:
                if (
                    child.is_dir()
                    and not child.name.startswith(".")
                    and child.name not in SKIP_DIRS
                ):
                    walk(child, depth + 1)

        walk(root, 0)
        return {"folders": folders[:200], "repos": repos[:100]}

    def find_files(self, query: str, extension: str = "") -> list[dict[str, object]]:
        """Files whose name contains every word of `query` (accents and case ignored)."""
        words = [w for w in _plain(query).split() if w]
        ext = extension.strip().lower().lstrip(".")
        root = self.root.resolve()
        found: list[dict[str, object]] = []
        scanned = 0
        for folder, dirs, files in os.walk(root):
            depth = len(Path(folder).relative_to(root).parts)
            dirs[:] = [] if depth >= FIND_DEPTH else [
                d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS
            ]  # fmt: skip
            for name in files:
                scanned += 1
                if scanned > FIND_MAX_SCANNED:
                    return found
                if name.startswith(".") or (ext and not name.lower().endswith("." + ext)):
                    continue
                plain = _plain(name)
                if all(w in plain for w in words):
                    path = Path(folder) / name
                    try:  # a broken link or one pointing outside must not stop the search
                        stat = path.stat()
                        relative = self.relative(path)
                    except (OSError, ValueError):
                        continue
                    found.append(
                        {
                            "path": relative,
                            "size_kb": round(stat.st_size / 1024, 1),
                            "modified": datetime.fromtimestamp(stat.st_mtime, UTC)
                            .date()
                            .isoformat(),
                        }
                    )
                    if len(found) >= FIND_MAX_RESULTS:
                        return found
        return found

    async def repos_overview(self) -> list[dict[str, object]]:
        """Local status of every repository (no fetch), for a quick briefing."""
        overview = []
        for repo in (await asyncio.to_thread(self.list_projects))["repos"]:
            try:
                status = await self.status(repo, fetch=False)
            except WorkspaceError as exc:
                overview.append({"repo": repo, "error": str(exc)[:200]})
                continue
            overview.append(
                {
                    "repo": repo,
                    "branch": status["branch"],
                    "uncommitted_changes": len(status["uncommitted_changes"]),  # type: ignore[arg-type]
                    "unpushed_commits": status["ahead"],
                    "last_commit": status["last_commit"],
                }
            )
        return overview

    def check_new_folder(self, relative: str) -> Path:
        """Validate a folder to create (shown in the approval before anything happens)."""
        path = self.resolve(relative)
        for part in PurePosixPath(relative.strip().replace("\\", "/")).parts:
            if INVALID_NAME.search(part) or part.endswith((" ", ".")) or len(part) > 120:
                raise WorkspaceError(f"Invalid folder name: {part!r}")
        if path.exists():
            raise WorkspaceError(f"Already exists: {relative}")
        return path

    def create_folder(self, relative: str) -> dict[str, str]:
        path = self.check_new_folder(relative)
        path.mkdir(parents=True)
        return {"status": "created", "path": self.relative(path)}

    # ---- git ----------------------------------------------------------------------------

    async def git(self, repo: Path, *args: str, timeout: int = GIT_TIMEOUT_S) -> str:
        command = [
            "git",
            "-c", "safe.directory=*",
            "-c", f"core.autocrlf={self._autocrlf}",
            "-c", "core.filemode=false",
            "-c", "credential.helper=",  # ignore host helpers (e.g. Windows manager)
        ]  # fmt: skip
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        if not env.get("GIT_CONFIG_GLOBAL"):
            env.pop("GIT_CONFIG_GLOBAL", None)  # compose passes "" when no identity is mounted
        if self._token:
            command += ["-c", f"credential.helper={TOKEN_HELPER}"]
            # SSH remotes (git@github.com:...) go through HTTPS with the token instead.
            command += ["-c", "url.https://github.com/.insteadOf=git@github.com:"]
            env["GITHUB_TOKEN"] = self._token
        process = await asyncio.create_subprocess_exec(
            *command,
            "-C",
            str(repo),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError:
            process.kill()
            raise WorkspaceError(f"git {args[0]} took too long") from None
        if process.returncode != 0:
            message = err.decode(errors="replace").strip() or out.decode(errors="replace").strip()
            raise WorkspaceError(f"git {args[0]} failed: {self._redact(message)[:500]}")
        return out.decode(errors="replace")

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "***") if self._token else text

    async def status(self, relative: str, *, fetch: bool = True) -> dict[str, object]:
        """Branch, changes not committed yet, and commits not pushed (or not pulled)."""
        repo = self.repo(relative)
        fetched = False
        if fetch:
            try:  # best effort: offline or no token still gives the local status
                await self.git(repo, "fetch", "--quiet", timeout=20)
                fetched = True
            except WorkspaceError:
                fetched = False
        branch = (await self.git(repo, "rev-parse", "--abbrev-ref", "HEAD")).strip()
        changes = [
            line for line in (await self.git(repo, "status", "--porcelain=v1")).splitlines() if line
        ]
        upstream = None
        ahead = behind = 0
        unpushed: list[str] = []
        try:
            upstream = (await self.git(repo, "rev-parse", "--abbrev-ref", "@{u}")).strip()
            counts = (
                await self.git(repo, "rev-list", "--left-right", "--count", "@{u}...HEAD")
            ).split()
            behind, ahead = int(counts[0]), int(counts[1])
            unpushed = (await self.git(repo, "log", "--oneline", "@{u}..HEAD")).splitlines()
        except WorkspaceError:
            upstream = None  # no upstream branch yet: everything is unpushed
            unpushed = (await self.git(repo, "log", "--oneline", "-10")).splitlines()
        last = (await self.git(repo, "log", "-1", "--format=%h %s (%cr)")).strip()
        return {
            "repo": self.relative(repo),
            "branch": branch,
            "upstream": upstream,
            "fetched": fetched,
            "ahead": ahead,
            "behind": behind,
            "unpushed_commits": unpushed[:30],
            "uncommitted_changes": changes[:100],
            "last_commit": last,
        }

    async def diff(self, relative: str) -> dict[str, object]:
        repo = self.repo(relative)
        stat = await self.git(repo, "diff", "HEAD", "--stat")
        text = await self.git(repo, "diff", "HEAD")
        untracked = (
            await self.git(repo, "ls-files", "--others", "--exclude-standard")
        ).splitlines()
        return {
            "repo": self.relative(repo),
            "stat": stat.strip(),
            "diff": text[:MAX_DIFF_CHARS],
            "truncated": len(text) > MAX_DIFF_CHARS,
            "untracked_files": untracked[:100],
        }

    async def commit(self, relative: str, message: str) -> dict[str, object]:
        repo = self.repo(relative)
        await self.git(repo, "add", "-A")
        await self.git(repo, "commit", "-m", message)
        head = (await self.git(repo, "log", "-1", "--format=%h %s")).strip()
        return {"status": "committed", "repo": self.relative(repo), "commit": head}

    async def push(self, relative: str) -> dict[str, object]:
        repo = self.repo(relative)
        branch = (await self.git(repo, "rev-parse", "--abbrev-ref", "HEAD")).strip()
        try:
            await self.git(repo, "rev-parse", "--abbrev-ref", "@{u}")
            args = ["push"]
        except WorkspaceError:
            args = ["push", "--set-upstream", "origin", branch]
        if not self._token:
            remote = (await self.git(repo, "remote", "get-url", "origin")).strip()
            if "github.com" in remote:
                raise WorkspaceError(
                    "Pushing to GitHub needs GITHUB_TOKEN in .env (a fine-grained token with "
                    "Contents: read and write); the user must add it and restart the API."
                )
        await self.git(repo, *args, timeout=PUSH_TIMEOUT_S)
        return {"status": "pushed", "repo": self.relative(repo), "branch": branch}
