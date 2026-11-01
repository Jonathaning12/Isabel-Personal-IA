"""`assistant doctor`: check that everything needed to run the assistant is in place.

Runs on the user's machine (reads the local .env) and checks, in order:
.env and API key → provider catalog → embedding dimension → Qdrant → Docker and
sandbox image → the API → its token → the voices (Gemini quota, local Piper).
Each failed check prints how to fix it.
"""

from collections.abc import Callable
from pathlib import Path

import httpx
from openai import OpenAI
from rich.console import Console
from rich.table import Table

from assistant.api.auth import client_token
from assistant.config import Settings
from assistant.memory.store import DOCUMENTS, USER_FACTS

Check = tuple[bool, str, str]  # (ok, detail, how to fix)


def _env() -> tuple[Check, Settings | None]:
    if not Path(".env").exists():
        return (False, "No existe .env", "cp .env.example .env y añade tu NEBIUS_API_KEY"), None
    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as exc:
        return (False, f"Configuración inválida: {exc}", "Revisa .env frente a .env.example"), None
    key = settings.api_key_name
    if not settings.inference_api_key:
        return (False, f"{key} vacía", f"Añade tu key en {key} dentro de .env"), None
    return (True, f"Encontrado, con {key} (proveedor: {settings.llm_provider})", ""), settings


def _nebius(settings: Settings) -> Check:
    client = OpenAI(
        base_url=settings.inference_base_url,
        api_key=settings.inference_api_key,
        timeout=20,
    )
    # Gemini lists its models as "models/<id>".
    ids = {m.id.removeprefix("models/") for m in client.models.list()}
    missing = [m for m in (settings.llm_model, settings.embed_model) if m not in ids]
    if missing:
        return (
            False,
            f"No están en el catálogo: {', '.join(missing)}",
            "Ejecuta scripts/verify_models.py",
        )
    return (True, f"{settings.llm_model} · {settings.embed_model}", "")


def _embedding(settings: Settings) -> Check:
    client = OpenAI(
        base_url=settings.inference_base_url,
        api_key=settings.inference_api_key,
        timeout=60,
    )
    dim = len(
        client.embeddings.create(model=settings.embed_model, input=["ping"]).data[0].embedding
    )
    if dim != settings.embed_dim:
        return (False, f"Dimensión {dim} ≠ EMBED_DIM={settings.embed_dim}", f"Pon EMBED_DIM={dim}")
    return (True, f"Dimensión {dim}", "")


def _qdrant(settings: Settings) -> Check:
    url = settings.qdrant_url.replace("://qdrant:", "://localhost:")
    collections = httpx.get(f"{url}/collections", timeout=5).json()["result"]["collections"]
    names = {c["name"] for c in collections}
    for name in (DOCUMENTS, USER_FACTS):
        if name in names:
            info = httpx.get(f"{url}/collections/{name}", timeout=5).json()["result"]
            size = info["config"]["params"]["vectors"]["size"]
            if size != settings.embed_dim:
                return (False, f"'{name}' tiene tamaño {size}", "Borra la colección y re-indexa")
    count = sum(1 for n in (DOCUMENTS, USER_FACTS) if n in names)
    return (True, f"Accesible en {url} · {count}/2 colecciones", "")


def _sandbox(settings: Settings) -> Check:
    import docker

    client = docker.from_env()
    client.ping()
    try:
        client.images.get(settings.sandbox_image)
    except docker.errors.ImageNotFound:
        return (False, f"Falta la imagen {settings.sandbox_image}", "docker compose build sandbox")
    return (True, f"Docker OK · imagen {settings.sandbox_image}", "")


def _api(settings: Settings) -> Check:
    health = httpx.get(f"{settings.api_url}/health", timeout=15).json()
    if health.get("status") != "ok":
        return (False, f"Estado: {health}", "docker compose logs api")
    return (True, f"{settings.api_url} · {settings.llm_provider} ok · qdrant ok", "")


def _auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {client_token(settings)}"}


def _token(settings: Settings) -> Check:
    reply = httpx.get(f"{settings.api_url}/habits", headers=_auth(settings), timeout=10)
    if reply.status_code == 401:
        return (False, "La API rechaza el token", "Revisa API_TOKEN en .env o data/api_token")
    reply.raise_for_status()
    source = "API_TOKEN (.env)" if settings.api_token.get_secret_value() else "data/api_token"
    return (True, f"Aceptado · {source}", "")


def _voice(settings: Settings) -> Check:
    status = httpx.get(f"{settings.api_url}/voice/status", headers=_auth(settings), timeout=10)
    status.raise_for_status()
    data = status.json()
    gemini = data.get("gemini", {})
    free = [m for m, s in gemini.items() if not s["paused_s"]]
    local = data.get("local")
    local_text = {"ok": "Piper listo", "off": "sin voz local"}.get(local, f"Piper: {local}")
    if free:
        return (True, f"Gemini disponible ({settings.tts_voice}) · {local_text}", "")
    if local == "ok":
        wait = min((s["paused_s"] for s in gemini.values()), default=0)
        detail = f"Cuota de Gemini agotada (vuelve en ~{wait // 60} min) · habla Piper"
        return (True, detail if gemini else "Habla Piper (voz local)", "")
    return (
        False,
        f"Sin voz natural · {local_text}",
        "docker compose up -d voice (o activa la facturación de Gemini)",
    )


def run_doctor(console: Console) -> bool:
    table = Table(title="Diagnóstico del asistente")
    table.add_column("")
    table.add_column("Comprobación")
    table.add_column("Detalle")
    table.add_column("Cómo arreglarlo", style="yellow")

    env_check, settings = _env()
    results: list[tuple[str, Check]] = [("Archivo .env", env_check)]
    if settings is not None:
        checks: list[tuple[str, Callable[[Settings], Check], str]] = [
            (
                f"{settings.llm_provider.capitalize()} y modelos",
                _nebius,
                "Revisa tu conexión y la key",
            ),
            ("Embeddings", _embedding, "El proveedor tarda o falla; reintenta en un momento"),
            ("Qdrant", _qdrant, "docker compose up -d qdrant"),
            ("Docker y sandbox", _sandbox, "Abre Docker Desktop"),
            ("API", _api, "docker compose up -d"),
            ("Token de la API", _token, "docker compose restart api"),
            ("Voz", _voice, "docker compose up -d voice"),
        ]
        with console.status("Comprobando…"):
            for label, check, fix in checks:
                try:
                    results.append((label, check(settings)))
                except Exception as exc:
                    results.append((label, (False, type(exc).__name__, fix)))

    for label, (ok, detail, fix) in results:
        table.add_row("[green]✔[/]" if ok else "[red]✘[/]", label, detail, fix)
    console.print(table)
    return all(ok for _, (ok, _, _) in results)
