"""API tests for the pause/resume endpoints: a computer-action result can never answer an
approval, and an approval can never answer a computer action."""

from types import SimpleNamespace

import pytest

from tests.unit.test_health import make_client


class Pending:
    def __init__(self, value):
        self.interrupts = [SimpleNamespace(value=value)]


class FakeGraph:
    def __init__(self, pending):
        self.pending = pending
        self.resumed = []

    async def aget_state(self, _config):
        return SimpleNamespace(tasks=[Pending(self.pending)] if self.pending else [])

    async def ainvoke(self, command, _config):
        self.resumed.append(command.resume)
        return {"messages": [{"role": "assistant", "content": "ok"}], "actions": [], "context": []}


APPROVAL = {"tool_call_id": "c1", "tool": "git_push", "args": {"repo": "x"}}
CLIENT = {
    "kind": "client_action",
    "tool_call_id": "c2",
    "tool": "media_control",
    "args": {"action": "next"},
}


@pytest.fixture
def client(monkeypatch, settings, tmp_path):
    with make_client(monkeypatch, settings, tmp_path) as test_client:
        yield test_client


def use(client, pending):
    graph = FakeGraph(pending)
    client.app.state.graph = graph
    return graph


def test_client_result_cannot_answer_an_approval(client):
    graph = use(client, APPROVAL)

    response = client.post(
        "/chat/t1/client-result", json={"tool_call_id": "c1", "result": {"decision": "approve"}}
    )

    assert response.status_code == 409
    assert graph.resumed == []


def test_confirm_cannot_answer_a_client_action(client):
    graph = use(client, CLIENT)

    assert client.post("/chat/t1/confirm", json={"decision": "approve"}).status_code == 409
    assert graph.resumed == []


def test_client_result_resumes_the_matching_action(client):
    graph = use(client, CLIENT)

    wrong = client.post("/chat/t1/client-result", json={"tool_call_id": "zzz", "result": {}})
    right = client.post(
        "/chat/t1/client-result", json={"tool_call_id": "c2", "result": {"status": "ok"}}
    )

    assert wrong.status_code == 409
    assert right.status_code == 200
    assert graph.resumed == [{"tool_call_id": "c2", "client_result": {"status": "ok"}}]
