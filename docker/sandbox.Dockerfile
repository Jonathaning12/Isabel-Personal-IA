# Sandbox image: runs Python code written by the agent, isolated from everything.
# The container is started with no network, a read-only filesystem, no capabilities,
# a non-root user and CPU/memory/time limits (see src/assistant/sandbox/docker_runner.py).
FROM python:3.12-slim

RUN pip install --no-cache-dir numpy==2.5.4 pandas==3.1.0

RUN useradd --uid 10001 --no-create-home sandbox
USER 10001
WORKDIR /work
