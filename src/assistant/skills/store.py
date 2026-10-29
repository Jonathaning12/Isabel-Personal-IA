"""Reusable skills: Python programs that worked once, saved to be run again by name.

A skill is like a function in the user's personal library: a name, a description, the
names of its parameters and the code. The code reads its inputs from a `params` dict,
which is injected when the skill runs. Skills live in data/skills.json on the user's disk.

Saving, running and deleting a skill are side-effect actions: they always need the
user's approval, and running one always happens inside the sandbox.
"""

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

NAME_PATTERN = r"^[a-z0-9][a-z0-9_]{1,39}$"
PARAM_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,39}$")


class Skill(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)
    description: str = Field(min_length=1, max_length=300)
    parameters: list[str] = Field(default_factory=list, max_length=10)
    code: str = Field(min_length=1, max_length=20_000)
    created_at: str = ""
    updated_at: str = ""
    runs: int = 0

    @field_validator("parameters")
    @classmethod
    def valid_parameter_names(cls, names: list[str]) -> list[str]:
        for name in names:
            if not PARAM_PATTERN.match(name):
                raise ValueError(f"Invalid parameter name: {name!r}")
        return names


class SkillError(ValueError):
    """Unknown skill or invalid parameters."""


def build_program(skill: Skill, params: dict[str, Any]) -> str:
    """The exact program that runs in the sandbox: params injected as JSON, then the code."""
    unknown = set(params) - set(skill.parameters)
    missing = set(skill.parameters) - set(params)
    if unknown or missing:
        raise SkillError(
            f"Skill '{skill.name}' expects parameters {skill.parameters}; "
            f"missing {sorted(missing)}, unknown {sorted(unknown)}"
        )
    payload = json.dumps(params, ensure_ascii=False)
    # json.loads of a string literal: parameter values can never become code.
    return f"import json\nparams = json.loads({payload!r})\n\n{skill.code}"


class SkillStore:
    def __init__(self, path: Path):
        self._path = path

    def _load(self) -> dict[str, Skill]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return {name: Skill.model_validate(data) for name, data in raw.items()}

    def _write(self, skills: dict[str, Skill]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: s.model_dump() for name, s in sorted(skills.items())}
        # Write to a temp file and rename: the file is never left half-written.
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    def list(self) -> list[Skill]:
        return list(self._load().values())

    def get(self, name: str) -> Skill:
        skill = self._load().get(name)
        if skill is None:
            raise SkillError(f"Unknown skill: {name}")
        return skill

    def save(self, skill: Skill) -> tuple[Skill, bool]:
        """Create or replace a skill. Returns (skill, created)."""
        skills = self._load()
        now = datetime.now(UTC).isoformat()
        existing = skills.get(skill.name)
        skill.created_at = existing.created_at if existing else now
        skill.updated_at = now
        skill.runs = existing.runs if existing else 0
        skills[skill.name] = skill
        self._write(skills)
        return skill, existing is None

    def record_run(self, name: str) -> None:
        skills = self._load()
        if name in skills:
            skills[name].runs += 1
            self._write(skills)

    def delete(self, name: str) -> bool:
        skills = self._load()
        if skills.pop(name, None) is None:
            return False
        self._write(skills)
        return True
