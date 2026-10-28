"""Integration tests for the Docker sandbox (needs Docker and the sandbox image).

Build the image first: docker compose build sandbox
"""

import pytest

from assistant.sandbox.docker_runner import DockerRunner

pytestmark = pytest.mark.integration


@pytest.fixture
def runner(settings) -> DockerRunner:
    settings.sandbox_timeout_s = 10
    settings.sandbox_max_output_bytes = 1000
    return DockerRunner(settings)


async def test_runs_python_and_returns_stdout(runner):
    result = await runner.run("print(sum(range(10)))")
    assert result.exit_code == 0
    assert result.stdout.strip() == "45"


async def test_libraries_are_available(runner):
    result = await runner.run("import pandas as pd; print(pd.Series([1, 2, 3]).mean())")
    assert result.stdout.strip() == "2.0"


async def test_network_is_blocked(runner):
    code = (
        "import urllib.request\n"
        "urllib.request.urlopen('https://example.com', timeout=3)\n"
        "print('NETWORK OK')"
    )
    result = await runner.run(code)
    assert result.exit_code != 0
    assert "NETWORK OK" not in result.stdout


async def test_infinite_loop_is_killed_at_timeout(runner):
    result = await runner.run("while True: pass", timeout_s=3)
    assert result.timed_out is True
    assert result.exit_code is None
    assert result.duration_ms < 10_000


async def test_cannot_write_outside_work(runner):
    result = await runner.run("open('/etc/hacked', 'w').write('x')")
    assert result.exit_code != 0
    assert "Read-only file system" in result.stderr or "Permission denied" in result.stderr


async def test_can_write_inside_work(runner):
    result = await runner.run(
        "open('/work/a.txt', 'w').write('ok'); print(open('/work/a.txt').read())"
    )
    assert result.stdout.strip() == "ok"


async def test_runs_as_non_root(runner):
    result = await runner.run("import os; print(os.getuid())")
    assert result.stdout.strip() == "10001"


async def test_host_files_are_not_visible(runner):
    result = await runner.run("import os; print(os.path.exists('/app/.env'), os.listdir('/work'))")
    assert result.stdout.strip() == "False []"


async def test_long_output_is_truncated(runner):
    result = await runner.run("print('x' * 5000)")
    assert result.truncated is True
    assert len(result.stdout) < 1100
