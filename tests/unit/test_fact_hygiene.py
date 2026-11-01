"""Unit tests for memory hygiene: outdated facts are replaced, and a reviewed tidy-up merges
duplicates and drops outdated facts."""

import json
from types import SimpleNamespace

from assistant.memory.facts import ConsolidationPlan, FactMemory, Merge

# Two topics: "where the user lives" (similar vectors) and "coffee" (a different direction).
VECTORS = {  # cosine within a topic ≈ 0.78: related, below the 0.9 duplicate threshold
    "El usuario vive en Monterrey.": [1, 0, 0, 0, 0, 0, 0, 0],
    "El usuario vive en Guadalajara.": [1, 0.8, 0, 0, 0, 0, 0, 0],
    "El usuario trabaja en Monterrey.": [1, 0, 0.8, 0, 0, 0, 0, 0],
    "Le gusta el café.": [0, 0, 0, 1, 0, 0, 0, 0],
    "Toma café cada mañana.": [0, 0, 0, 1, 0.8, 0, 0, 0],
    "Le gusta el café, cada mañana.": [0, 0, 0, 1, 0.4, 0, 0, 0],
}


class TopicEmbedder:
    async def embed(self, texts, **kwargs):
        return [[float(x) for x in VECTORS[t]] for t in texts]


class ScriptedChat:
    """Answers each call with the next scripted reply (a function of the prompt or a string)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        reply = self.replies.pop(0) if self.replies else '{"replaces": []}'
        content = reply(messages) if callable(reply) else reply
        return SimpleNamespace(content=content, tool_calls=None)


def memory(store, settings, *replies) -> FactMemory:
    return FactMemory(store, TopicEmbedder(), ScriptedChat(*replies), settings)


def first_id(messages) -> str:
    """The id of the first EXISTING fact shown to the model."""
    return messages[-1]["content"].split("[", 1)[1].split("]", 1)[0]


async def test_a_new_fact_replaces_the_outdated_one(store, settings):
    facts = memory(store, settings, lambda m: json.dumps({"replaces": [first_id(m)]}))
    old = await facts.remember("El usuario vive en Monterrey.", "personal")

    new = await facts.remember("El usuario vive en Guadalajara.", "personal")

    assert new.replaced == [old.id]
    assert [f["fact"] for f in await facts.list()] == ["El usuario vive en Guadalajara."]


async def test_related_facts_that_can_both_be_true_are_kept(store, settings):
    facts = memory(store, settings)  # the model says nothing is replaced
    await facts.remember("El usuario vive en Monterrey.")
    await facts.remember("El usuario trabaja en Monterrey.")

    assert len(await facts.list()) == 2


async def test_unrelated_facts_do_not_ask_the_model(store, settings):
    facts = memory(store, settings)
    await facts.remember("El usuario vive en Monterrey.")
    await facts.remember("Le gusta el café.")

    assert facts._chat.calls == []


async def test_ids_the_model_invents_are_ignored(store, settings):
    facts = memory(store, settings, '{"replaces": ["not-a-real-id"]}')
    await facts.remember("El usuario vive en Monterrey.")
    await facts.remember("El usuario vive en Guadalajara.")

    assert len(await facts.list()) == 2


async def test_tidy_up_is_only_a_proposal_until_applied(store, settings):
    facts = memory(store, settings)
    coffee = await facts.remember("Le gusta el café.")
    habit = await facts.remember("Toma café cada mañana.")
    city = await facts.remember("El usuario vive en Monterrey.")
    proposal = {
        "merge": [
            {"ids": [coffee.id, habit.id, "ghost"], "fact": "Le gusta el café, cada mañana."}
        ],
        "drop": [city.id, coffee.id],  # coffee is already merged: ignored here
    }
    facts._chat.replies = [json.dumps(proposal)]

    plan = await facts.plan_consolidation()

    assert plan.merge[0].ids == [coffee.id, habit.id]
    assert plan.drop == [city.id]
    assert len(await facts.list()) == 3  # nothing changed yet

    assert await facts.apply_consolidation(plan) == {"merged": 1, "dropped": 1}
    remaining = await facts.list()
    assert [(f["fact"], f["source"]) for f in remaining] == [
        ("Le gusta el café, cada mañana.", "consolidated")
    ]


async def test_a_stale_plan_skips_facts_that_are_gone(store, settings):
    facts = memory(store, settings)
    coffee = await facts.remember("Le gusta el café.")
    habit = await facts.remember("Toma café cada mañana.")
    await facts.forget(habit.id)
    plan = ConsolidationPlan(
        merge=[Merge(ids=[coffee.id, habit.id], fact="Le gusta el café, cada mañana.")]
    )

    assert await facts.apply_consolidation(plan) == {"merged": 0, "dropped": 0}
    assert len(await facts.list()) == 1
