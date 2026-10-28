"""Sandbox interface. Any backend (Docker today, OpenShell later) implements SandboxRunner."""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int | None  # None when the run was killed by the timeout
    duration_ms: int
    timed_out: bool
    truncated: bool


class SandboxRunner(Protocol):
    async def run(self, code: str, *, timeout_s: int | None = None) -> SandboxResult: ...

    def limits(self) -> dict[str, object]:
        """Human-readable limits, shown to the user before they approve a run."""
        ...
