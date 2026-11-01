"""Unit tests for the speed fixes: recent history only, learning only from personal
messages, and the Gemini reasoning level."""

from assistant.agent.graph import OLD_TOOL_RESULT_CHARS, build_system_prompt, recent_messages
from assistant.api.routes.chat import talks_about_user
from assistant.llm.chat import ChatClient


def conversation(turns: int) -> list[dict]:
    messages = []
    for i in range(turns):
        messages += [
            {"role": "user", "content": f"pregunta {i}"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}"}]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": "x" * 2000},
            {"role": "assistant", "content": f"respuesta {i}"},
        ]
    return messages


def test_short_conversations_are_sent_whole():
    messages = conversation(3)
    window, trimmed = recent_messages(messages, 6)
    assert not trimmed and len(window) == len(messages)


def test_only_the_last_turns_are_sent_and_old_tool_output_is_shortened():
    window, trimmed = recent_messages(conversation(20), 6)

    assert trimmed
    assert window[0] == {"role": "user", "content": "pregunta 14"}  # starts at a whole turn
    old_tools = [m for m in window[:-4] if m["role"] == "tool"]
    assert all(len(m["content"]) == OLD_TOOL_RESULT_CHARS + 1 for m in old_tools)
    assert window[-2]["content"] == "x" * 2000  # the current turn keeps its full result


def test_the_conversation_summary_goes_into_the_prompt():
    prompt = build_system_prompt([], [], thread_summary="El usuario planea un viaje a Oaxaca.")
    assert "EARLIER IN THIS CONVERSATION" in prompt and "Oaxaca" in prompt


def test_learning_only_from_messages_about_the_user():
    for message in [
        "Trabajo como desarrollador web",
        "Me encanta el café de olla",
        "Mi hermana se llama Laura",
    ]:
        assert talks_about_user(message), message
    for message in [
        "pon música de Maluma",
        "¿qué hora es en Tokio ahora?",
        "abre Visual Studio Code",
    ]:
        assert not talks_about_user(message), message


def test_gemini_answers_use_the_configured_reasoning_level(settings):
    gemini = settings.model_copy(update={"llm_provider": "gemini", "llm_reasoning_effort": "low"})
    client = ChatClient(None, gemini)

    normal = client._params([], thinking=True, max_tokens=None, tools=None)
    helper = client._params([], thinking=False, max_tokens=None, tools=None, timeout=8)

    assert normal["reasoning_effort"] == "low"
    assert helper["reasoning_effort"] == "minimal" and helper["timeout"] == 8
