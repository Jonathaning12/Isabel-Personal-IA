"""Information from the internet: weather (Open-Meteo) and web search (Gemini + Google).

- Weather uses Open-Meteo: free, no API key, no account. Only the city name and its
  coordinates are sent.
- Web search asks Gemini with its built-in Google Search tool ("grounding") and returns
  the answer plus its sources. Only the search question is sent (no notes, no memory).
"""

import logging
from urllib.parse import quote

import httpx

from assistant.config import Settings

logger = logging.getLogger("assistant.web")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 15

# WMO weather codes → Spanish (https://open-meteo.com/en/docs).
WEATHER_CODES = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "niebla", 48: "niebla con escarcha", 51: "llovizna ligera", 53: "llovizna",
    55: "llovizna intensa", 61: "lluvia ligera", 63: "lluvia", 65: "lluvia fuerte",
    66: "lluvia helada", 67: "lluvia helada fuerte", 71: "nieve ligera", 73: "nieve",
    75: "nieve fuerte", 80: "chubascos ligeros", 81: "chubascos", 82: "chubascos fuertes",
    95: "tormenta", 96: "tormenta con granizo", 99: "tormenta fuerte con granizo",
}  # fmt: skip


class WebError(RuntimeError):
    """The web service failed or returned nothing usable."""


async def get_weather(place: str, days: int = 1) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        geo = await client.get(GEOCODE_URL, params={"name": place, "count": 1, "language": "es"})
        geo.raise_for_status()
        results = geo.json().get("results") or []
        if not results:
            raise WebError(f"No encontré la ciudad «{place}».")
        city = results[0]
        forecast = await client.get(
            FORECAST_URL,
            params={
                "latitude": city["latitude"],
                "longitude": city["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": days,
            },
        )
        forecast.raise_for_status()
        data = forecast.json()
    now = data.get("current", {})
    daily = data.get("daily", {})
    return {
        "place": ", ".join(
            filter(None, [city.get("name"), city.get("admin1"), city.get("country")])
        ),
        "now": {
            "temperature_c": now.get("temperature_2m"),
            "feels_like_c": now.get("apparent_temperature"),
            "humidity_pct": now.get("relative_humidity_2m"),
            "wind_kmh": now.get("wind_speed_10m"),
            "sky": WEATHER_CODES.get(now.get("weather_code"), "desconocido"),
        },
        "days": [
            {
                "date": date,
                "sky": WEATHER_CODES.get(code, "desconocido"),
                "max_c": tmax,
                "min_c": tmin,
                "rain_chance_pct": rain,
            }
            for date, code, tmax, tmin, rain in zip(
                daily.get("time", []),
                daily.get("weather_code", []),
                daily.get("temperature_2m_max", []),
                daily.get("temperature_2m_min", []),
                daily.get("precipitation_probability_max", []),
                strict=False,
            )
        ],
    }


async def web_search(query: str, settings: Settings) -> dict[str, object]:
    """Live web search with the best source available:
    1. Gemini + Google Search grounding (needs a Gemini plan with Search quota);
    2. Brave Search API, if BRAVE_API_KEY is set (free tier available);
    3. Wikipedia (free, no key): general knowledge only, not news or prices.
    """
    errors: list[str] = []
    if settings.llm_provider == "gemini":
        try:
            return await _gemini_search(query, settings)
        except WebError as exc:
            errors.append(str(exc))
    brave_key = settings.brave_api_key.get_secret_value()
    if brave_key:
        try:
            return await _brave_search(query, brave_key)
        except (WebError, httpx.HTTPError) as exc:
            errors.append(f"brave: {exc}")
    try:
        result = await _wikipedia_search(query)
        result["note"] = (
            "Live web search is unavailable (the Gemini key has no Google Search quota and no "
            "BRAVE_API_KEY is set); these are Wikipedia results, which may be outdated for news "
            "or prices. Tell the user."
        )
        return result
    except (WebError, httpx.HTTPError) as exc:
        errors.append(f"wikipedia: {exc}")
    logger.warning("web_search_failed %s", "; ".join(errors))
    raise WebError("La búsqueda web no está disponible ahora mismo.")


async def _brave_search(query: str, key: str) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        reply = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 6, "search_lang": "es"},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        reply.raise_for_status()
    results = reply.json().get("web", {}).get("results", [])
    if not results:
        raise WebError("no results")
    return {
        "results": [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", "")[:400],
            }
            for r in results[:6]
        ],
        "source": "Brave Search",
    }


async def _wikipedia_search(query: str) -> dict[str, object]:
    async with httpx.AsyncClient(
        timeout=TIMEOUT_S, headers={"User-Agent": "Isabel-assistant/0.1"}
    ) as client:
        reply = await client.get(
            "https://es.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": 3,
            },
        )
        reply.raise_for_status()
        hits = reply.json().get("query", {}).get("search", [])
        if not hits:
            raise WebError("no results")
        results = []
        for hit in hits:
            title = hit["title"]
            slug = quote(title.replace(" ", "_"), safe="")  # titles may contain / ? #
            summary = await client.get(f"https://es.wikipedia.org/api/rest_v1/page/summary/{slug}")
            extract = summary.json().get("extract", "") if summary.status_code == 200 else ""
            results.append(
                {
                    "title": title,
                    "url": f"https://es.wikipedia.org/wiki/{slug}",
                    "snippet": extract[:600],
                }
            )
    return {"results": results, "source": "Wikipedia"}


async def _gemini_search(query: str, settings: Settings) -> dict[str, object]:
    """Gemini with Google Search grounding: a short answer plus the pages it used."""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": query}]}],
        "systemInstruction": {
            "parts": [
                {
                    "text": "Answer in Spanish, briefly and factually, using Google Search. "
                    "Include dates for news and prices."
                }
            ]
        },
        "tools": [{"google_search": {}}],
    }
    errors = []
    async with httpx.AsyncClient(timeout=30) as client:
        for model in dict.fromkeys([settings.search_model, settings.llm_model]):
            url = f"{settings.gemini_native_url}/models/{model}:generateContent"
            try:
                reply = await client.post(
                    url, headers={"x-goog-api-key": settings.inference_api_key}, json=payload
                )
                reply.raise_for_status()
                candidate = reply.json()["candidates"][0]
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                errors.append(f"{model}: {type(exc).__name__}")
                continue
            text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))
            chunks = candidate.get("groundingMetadata", {}).get("groundingChunks", [])
            sources = [
                {"title": c["web"].get("title", ""), "url": c["web"].get("uri", "")}
                for c in chunks
                if "web" in c
            ][:6]
            return {"answer": text.strip()[:4000], "sources": sources, "source": "Google (Gemini)"}
    raise WebError("gemini: " + "; ".join(errors))
