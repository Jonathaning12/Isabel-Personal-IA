"""Unit tests for learning by watching: music habits, background fact learning, and how
both reach the agent's prompt."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from assistant.agent.graph import build_system_prompt
from assistant.memory.habits import HabitLog, artist_from_play
from tests.unit.test_chat_api import FakeGraph, use
from tests.unit.test_health import make_client

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


def test_top_artists_counts_recent_plays_case_insensitively(tmp_path):
    log = HabitLog(tmp_path / "habits.json")
    for artist in ["Luis Miguel", "luis miguel", "Maluma", "Luis Miguel"]:
        log.record_music(artist, at=NOW - timedelta(days=1))
    log.record_music("Queen", at=NOW - timedelta(days=90))  # too old

    assert log.top_artists(now=NOW) == [("Luis Miguel", 3), ("Maluma", 1)]


def test_clear_forgets_everything(tmp_path):
    log = HabitLog(tmp_path / "habits.json")
    log.record_music("Maluma")
    log.clear()

    assert log.top_artists() == [] and log.describe() == []


def test_a_broken_file_counts_as_empty(tmp_path):
    path = tmp_path / "habits.json"
    path.write_text("{not json", encoding="utf-8")

    assert HabitLog(path).top_artists() == []


@pytest.mark.parametrize(
    ("args", "result", "expected"),
    [
        (
            {"kind": "track", "query": "Parce"},
            {"playing": "Parce — Maluma, Justin Quiles"},
            ("Maluma", "Parce"),
        ),
        (
            {"kind": "track", "query": "Nosotros", "artist": "Luis Miguel"},
            {"playing": "Nosotros — Luis Miguel"},
            ("Luis Miguel", "Nosotros"),
        ),
        ({"kind": "artist", "query": "Queen"}, {"playing": "Queen"}, ("Queen", "")),
        ({"kind": "playlist", "query": "Lo-fi"}, {"playing": "Lo-fi beats"}, ("", "Lo-fi beats")),
    ],
)
def test_artist_from_play(args, result, expected):
    assert artist_from_play(args, result) == expected


def test_prompt_includes_habits_and_the_users_name():
    prompt = build_system_prompt(
        [], [], habits=["Most played artists: Luis Miguel (3)."], user_name="Jonathan"
    )

    assert "LEARNED HABITS" in prompt and "Luis Miguel (3)" in prompt
    assert "The user's name is Jonathan" in prompt


def test_prompt_without_habits_has_no_habits_block():
    assert "LEARNED HABITS (observed" not in build_system_prompt([], [])


SPOTIFY = {
    "kind": "client_action",
    "tool_call_id": "c9",
    "tool": "spotify_play",
    "args": {"query": "Parce", "artist": "Maluma", "kind": "track"},
}


@pytest.fixture
def client(monkeypatch, settings, tmp_path):
    with make_client(monkeypatch, settings, tmp_path) as test_client:
        yield test_client


def test_a_song_that_really_played_becomes_a_habit(client):
    use(client, SPOTIFY)
    result = {"status": "ok", "playing": "Parce — Maluma, Justin Quiles"}

    client.post("/chat/t1/client-result", json={"tool_call_id": "c9", "result": result})

    assert client.get("/habits").json() == {"artists": [{"name": "Maluma", "plays": 1}]}
    assert client.delete("/habits").status_code == 200
    assert client.get("/habits").json() == {"artists": []}


def test_a_failed_play_is_not_a_habit(client):
    use(client, SPOTIFY)
    result = {"status": "error", "message": "Spotify respondió 404."}

    client.post("/chat/t1/client-result", json={"tool_call_id": "c9", "result": result})

    assert client.get("/habits").json() == {"artists": []}


class ChatGraph(FakeGraph):
    async def ainvoke(self, turn, _config):
        self.resumed.append(turn)
        return {"messages": [{"role": "assistant", "content": "ok"}], "actions": [], "context": []}


class FakeFacts:
    def __init__(self):
        self.learned = []

    async def learn(self, message, source="conversation"):
        self.learned.append((message, source))
        return [SimpleNamespace(fact="x")]


def chat_with(client):
    graph = ChatGraph(None)
    client.app.state.graph = graph
    facts = FakeFacts()
    client.app.state.facts = facts
    return graph, facts


def test_chat_learns_facts_from_the_users_words_in_the_background(client):
    graph, facts = chat_with(client)

    client.post(
        "/chat",
        json={"message": "Trabajo como desarrollador web en Monterrey", "user_name": "Jonathan"},
    )

    assert facts.learned == [("Trabajo como desarrollador web en Monterrey", "learned")]
    assert graph.resumed[0]["user_name"] == "Jonathan"


def test_automatic_and_short_messages_are_not_learned_from(client):
    _, facts = chat_with(client)

    client.post(
        "/chat", json={"message": "[automatic morning greeting] Buenos días", "automatic": True}
    )
    client.post("/chat", json={"message": "pon música"})

    assert facts.learned == []


def test_auto_learn_can_be_turned_off(client):
    _, facts = chat_with(client)
    client.app.state.settings = client.app.state.settings.model_copy(update={"auto_learn": False})

    client.post("/chat", json={"message": "Trabajo como desarrollador web en Monterrey"})

    assert facts.learned == []
