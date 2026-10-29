"""`assistant doctor`: check that everything needed to run the assistant is in place.

Runs on the user's machine (reads the local .env) and checks, in order:
.env and API key → Nebius catalog → embedding dimension → Qdrant → Docker and
sandbox image → the API. Each failed check prints how to fix it.
"""

from collections.abc import Callable
from pathlib import Path

import httpx
from openai import OpenAI
from rich.console import Console
from rich.table import Table

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
    if not settings.nebius_api_key.get_secret_value():
        return (False, "NEBIUS_API_KEY vacía", "Añade tu key de Nebius en .env"), None
    return (True, "Encontrado, con NEBIUS_API_KEY", ""), settings


def _nebius(settings: Settings) -> Check:
    client = OpenAI(
        base_url=settings.nebius_base_url,
        api_key=settings.nebius_api_key.get_secret_value(),
        timeout=20,
    )
    ids = {m.id for m in client.models.list()}
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
        base_url=settings.nebius_base_url,
        api_key=settings.nebius_api_key.get_secret_value(),
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
    return (True, f"{settings.api_url} · nebius ok · qdrant ok", "")


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
            ("Nebius y modelos", _nebius, "Revisa tu conexión y la key"),
            ("Embeddings", _embedding, "Nebius tarda o falla; reintenta en un momento"),
            ("Qdrant", _qdrant, "docker compose up -d qdrant"),
            ("Docker y sandbox", _sandbox, "Abre Docker Desktop"),
            ("API", _api, "docker compose up -d"),
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
