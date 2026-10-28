"""Run untrusted Python code in a fresh, locked-down Docker container.

Every run gets a brand-new container that is deleted afterwards. Isolation:
- no network (network_mode="none")
- read-only filesystem; only /work and /tmp are writable, in memory (tmpfs)
- non-root user, all Linux capabilities dropped, no privilege escalation
- memory, CPU and process limits, plus a wall-clock timeout that kills the container
- nothing from the host is mounted: no home folder, no .env, no Docker socket
"""

import asyncio
import time
from typing import Any

import docker
import requests
from docker.errors import DockerException

from assistant.config import Settings
from assistant.sandbox.base import SandboxResult


class SandboxError(RuntimeError):
    """The sandbox could not be started (Docker unavailable, image missing...)."""


def _truncate(data: bytes, limit: int) -> tuple[str, bool]:
    if len(data) <= limit:
        return data.decode("utf-8", errors="replace"), False
    return data[:limit].decode("utf-8", errors="replace") + "\n…[output truncated]", True


class DockerRunner:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: Any = None

    def limits(self) -> dict[str, object]:
        s = self._settings
        return {
            "network": False,
            "host_files": False,
            "memory": s.sandbox_memory,
            "cpus": s.sandbox_cpus,
            "timeout_s": s.sandbox_timeout_s,
        }

    def _docker(self) -> Any:
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException as exc:
                raise SandboxError(f"Docker is not available: {exc}") from exc
        return self._client

    async def run(self, code: str, *, timeout_s: int | None = None) -> SandboxResult:
        timeout = timeout_s or self._settings.sandbox_timeout_s
        return await asyncio.to_thread(self._run_sync, code, timeout)

    def _run_sync(self, code: str, timeout_s: int) -> SandboxResult:
        s = self._settings
        start = time.perf_counter()
        try:
            container = self._docker().containers.run(
                s.sandbox_image,
                ["python", "-I", "-c", code],
                detach=True,
                network_mode="none",
                read_only=True,
                tmpfs={"/work": "rw,size=64m,mode=1777", "/tmp": "rw,size=16m,mode=1777"},
                working_dir="/work",
                user="10001:10001",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                pids_limit=128,
                mem_limit=s.sandbox_memory,
                nano_cpus=int(s.sandbox_cpus * 1e9),
                environment={"PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp"},
                labels={"assistant.sandbox": "1"},
            )
        except DockerException as exc:
            raise SandboxError(f"Could not start the sandbox: {exc}") from exc

        timed_out = False
        exit_code: int | None = None
        try:
            try:
                exit_code = container.wait(timeout=timeout_s)["StatusCode"]
            except requests.exceptions.RequestException:
                timed_out = True
                container.kill()
            limit = s.sandbox_max_output_bytes
            stdout, out_cut = _truncate(container.logs(stdout=True, stderr=False), limit)
            stderr, err_cut = _truncate(container.logs(stdout=False, stderr=True), limit)
        finally:
            container.remove(force=True)

        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=int((time.perf_counter() - start) * 1000),
            timed_out=timed_out,
            truncated=out_cut or err_cut,
        )
