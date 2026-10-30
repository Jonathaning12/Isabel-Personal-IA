"""The user's Obsidian vault: read, search and write Markdown notes, safely.

The vault folder is mounted into the API container (docker-compose → /vault). Every path
the agent gives is relative to the vault root and is checked before use:
- only `.md` files, never hidden folders such as `.obsidian` or `.trash`;
- no absolute paths, no `..`, and the resolved real path must stay inside the vault
  (this also blocks symlinks that point outside).
Reading is free; writing goes through the approval flow (see tools/registry.py), and
before a note is overwritten its previous content is copied to data/note-backups/.
"""

import hashlib
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

MAX_READ_CHARS = 20_000
MAX_LIST = 200
MAX_MATCHES = 40
TASK_LINE = re.compile(r"^\s*[-*+]\s+\[ \]\s+(.+)$")

WriteMode = Literal["create", "append", "overwrite"]


class VaultError(ValueError):
    """Invalid path, missing note, or a write that is not allowed."""


@dataclass
class NoteInfo:
    path: str
    size: int
    modified: str


class Vault:
    def __init__(self, root: Path, backups: Path):
        self.root = root
        self._backups = backups

    # ---- paths --------------------------------------------------------------------------

    def resolve(self, relative: str) -> Path:
        """Vault-relative POSIX path → absolute path inside the vault, or VaultError."""
        rel = PurePosixPath(relative.strip().replace("\\", "/"))
        if not relative.strip() or rel.is_absolute() or re.match(r"^[A-Za-z]:", str(rel)):
            raise VaultError(
                f"Use a path relative to the vault, e.g. 'Proyectos/idea.md': {relative}"
            )
        if any(part in ("..", "") or part.startswith(".") for part in rel.parts):
            raise VaultError(f"Hidden folders and '..' are not allowed: {relative}")
        if rel.suffix.lower() != ".md":
            raise VaultError(f"Only Markdown notes (.md) are allowed: {relative}")
        root = self.root.resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            raise VaultError(f"Path outside the vault: {relative}")
        return path

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def _notes(self) -> list[Path]:
        root = self.root.resolve()
        notes = []
        for p in root.rglob("*.md"):
            if not p.is_file() or any(part.startswith(".") for part in p.relative_to(root).parts):
                continue
            # Skip links (symlinks, junctions) whose target is outside the vault.
            if not p.resolve().is_relative_to(root):
                continue
            notes.append(p)
        return notes

    # ---- reading ------------------------------------------------------------------------

    def all_paths(self) -> list[str]:
        """Every note in the vault (uncapped; for sync and counts, not for the model)."""
        return [self.relative(p) for p in self._notes()]

    def list_notes(self, folder: str = "", query: str = "") -> list[NoteInfo]:
        """Notes, most recently modified first, optionally filtered by folder / name.
        Capped at MAX_LIST: this is what the model sees."""
        prefix = folder.strip().strip("/").replace("\\", "/").lower()
        needle = query.strip().lower()
        notes = []
        for path in self._notes():
            rel = self.relative(path)
            if prefix and not rel.lower().startswith(prefix + "/"):
                continue
            if needle and needle not in rel.lower():
                continue
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds")
            notes.append(NoteInfo(rel, stat.st_size, modified))
        notes.sort(key=lambda n: n.modified, reverse=True)
        return notes[:MAX_LIST]

    def read(self, relative: str) -> dict[str, object]:
        path = self.resolve(relative)
        if not path.is_file():
            raise VaultError(f"Note not found: {relative}")
        text = path.read_text(encoding="utf-8", errors="replace")
        return {
            "path": self.relative(path),
            "content": text[:MAX_READ_CHARS],
            "truncated": len(text) > MAX_READ_CHARS,
        }

    def search(self, text: str) -> list[dict[str, object]]:
        """Case-insensitive literal search, line by line (complements the semantic search)."""
        needle = text.strip().lower()
        if not needle:
            raise VaultError("Empty search")
        matches: list[dict[str, object]] = []
        for path in self._notes():
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if needle in line.lower():
                    matches.append(
                        {"path": self.relative(path), "line": number, "text": line.strip()[:300]}
                    )
                    if len(matches) >= MAX_MATCHES:
                        return matches
        return matches

    def open_tasks(self) -> list[dict[str, object]]:
        """Unchecked Markdown tasks (`- [ ] ...`) across the vault."""
        tasks: list[dict[str, object]] = []
        for path in self._notes():
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                match = TASK_LINE.match(line)
                if match:
                    tasks.append(
                        {
                            "path": self.relative(path),
                            "line": number,
                            "task": match.group(1).strip()[:300],
                        }
                    )
                    if len(tasks) >= MAX_MATCHES * 2:
                        return tasks
        return tasks

    def snapshot(self, relative: str, max_chars: int = 4000) -> dict[str, object]:
        """What the note looks like now, shown in the approval card before a write.
        It is part of the approval fingerprint: if the note changes, the approval is stale."""
        path = self.resolve(relative)
        if not path.is_file():
            return {"exists": False}
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")  # for display
        return {
            "exists": True,
            "chars": len(text),
            "current": text[:max_chars],
            # Any edit anywhere in the note changes this, so the approval goes stale.
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    # ---- writing (only after approval) --------------------------------------------------

    def write(self, relative: str, content: str, mode: WriteMode) -> dict[str, object]:
        path = self.resolve(relative)
        exists = path.is_file()
        if mode == "create" and exists:
            raise VaultError(f"The note already exists; use append or overwrite: {relative}")
        if mode == "overwrite" and not exists:
            raise VaultError(f"Note not found: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        if mode == "overwrite":
            # Unique folder per backup (microseconds + random), never overwriting an old one.
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + "-" + uuid.uuid4().hex[:6]
            target = self._backups / stamp / self.relative(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with path.open("rb") as source, target.open("xb") as copy:
                shutil.copyfileobj(source, copy)
            backup = str(target)
        new = (content.rstrip("\n") + "\n").encode("utf-8")
        if mode == "append" and exists:
            # Only add bytes at the end: the existing note (its encoding, its line endings)
            # is never rewritten, so an append cannot damage it.
            with path.open("rb+") as note:
                note.seek(0, 2)
                size = note.tell()
                if size:
                    note.seek(size - 1)
                    needs_newline = note.read(1) != b"\n"
                    note.seek(0, 2)
                    if needs_newline:
                        note.write(b"\n")
                note.write(new)
        else:
            path.write_bytes(new)
        return {"path": self.relative(path), "mode": mode, "backup": backup}
