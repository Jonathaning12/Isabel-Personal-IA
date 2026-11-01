"""Unit tests for episodes: when a conversation is summarized, one summary per thread,
and only OTHER conversations come back as context."""

from assistant.agent.graph import build_system_prompt
from assistant.memory.episodes import EpisodeMemory, due_for_summary, transcript
from tests.conftest import FakeChat


def turns(n: int) -> list[dict]:
    messages = []
    for i in range(n):
        messages += [
            {"role": "user", "content": f"pregunta {i}"},
            {"role": "assistant", "content": f"respuesta {i}"},
        ]
    return messages


def test_summaries_at_the_second_turn_then_every_three():
    assert [n for n in range(1, 10) if due_for_summary(turns(n))] == [2, 5, 8]


def test_transcript_keeps_only_the_words_said():
    messages = [
        {"role": "user", "content": "pon música"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": '{"status": "ok"}'},
        {"role": "assistant", "content": "Listo, suena Queen."},
    ]
    assert transcript(messages) == "Usuario: pon música\nIsabel: Listo, suena Queen."


async def test_one_summary_per_conversation_and_others_come_back(store, fake_embedder, settings):
    chat = FakeChat("El usuario pidió ideas para el cumpleaños de su mamá.")
    episodes = EpisodeMemory(
        store, fake_embedder, chat, settings.model_copy(update={"episode_min_score": 0.0})
    )

    await episodes.summarize("thread-a", turns(2))
    await episodes.summarize("thread-a", turns(5))  # updated, not duplicated
    listed = await episodes.list()

    assert len(listed) == 1 and listed[0]["thread_id"] == "thread-a"
    vector = (await fake_embedder.embed(["cumpleaños"]))[0]
    assert await episodes.relevant(vector, "thread-a") == []  # not the current conversation
    found = await episodes.relevant(vector, "thread-b")
    assert len(found) == 1 and found[0].endswith("cumpleaños de su mamá.")
    assert await episodes.forget(listed[0]["id"]) is True
    assert await episodes.list() == []


def test_prompt_includes_past_conversations():
    prompt = build_system_prompt(
        [], [], episodes=["(2026-10-24) El usuario pidió ideas de regalo."]
    )
    assert "PAST CONVERSATIONS" in prompt and "ideas de regalo" in prompt
