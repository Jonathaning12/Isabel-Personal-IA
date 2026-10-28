"""Terminal interface (Typer + Rich). It talks to the local FastAPI backend over HTTP.

Commands: ingest, ask, search, remember, memory (facts / docs / forget / delete-doc).
"""

import os
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from assistant.cli import messages as msg
from assistant.ingest.loaders import SUPPORTED_EXTENSIONS

app = typer.Typer(help="Asistente personal de IA privado.", no_args_is_help=True)
memory_app = typer.Typer(help="Ver y gestionar la memoria del asistente.", no_args_is_help=True)
app.add_typer(memory_app, name="memory")
console = Console()

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
UPLOAD_BATCH = 10


def _request(method: str, path: str, *, timeout: float = 120, **kwargs: Any) -> dict:
    try:
        response = httpx.request(method, f"{API_URL}{path}", timeout=timeout, **kwargs)
    except httpx.ConnectError:
        console.print(msg.API_UNREACHABLE.format(url=API_URL))
        raise typer.Exit(1) from None
    if response.status_code >= 400:
        detail = response.json().get("detail") if response.content else ""
        console.print(msg.API_ERROR.format(status=response.status_code, detail=detail))
        raise typer.Exit(1)
    return response.json()


def _collect_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        files += [p for p in candidates if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
    return files


def _source_name(path: Path) -> str:
    """Relative path when possible, so the same file always maps to the same document."""
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path.resolve())


@app.command()
def ingest(paths: Annotated[list[Path], typer.Argument(help="Archivos o carpetas")]) -> None:
    """Indexa tus documentos (.md, .txt, .pdf) en la memoria local."""
    files = _collect_files(paths)
    if not files:
        console.print(msg.NO_FILES)
        raise typer.Exit(1)

    results: list[dict] = []
    with console.status(f"Indexando {len(files)} archivo(s)…"):
        for i in range(0, len(files), UPLOAD_BATCH):
            batch = files[i : i + UPLOAD_BATCH]
            upload = [("files", (_source_name(f), f.read_bytes())) for f in batch]
            results += _request("POST", "/ingest", files=upload, timeout=600)["results"]

    table = Table(title=msg.INGEST_TITLE)
    table.add_column("Archivo")
    table.add_column("Estado")
    table.add_column("Fragmentos", justify="right")
    for r in results:
        status = msg.STATUS_LABELS.get(r["status"], r["status"])
        note = f" [dim]{r['message']}[/]" if r.get("message") else ""
        table.add_row(r["source_path"], status + note, str(r["chunks"] or ""))
    console.print(table)
    counts = {s: sum(r["status"] == s for r in results) for s in ("indexed", "unchanged")}
    console.print(
        msg.INGEST_SUMMARY.format(
            indexed=counts["indexed"],
            unchanged=counts["unchanged"],
            other=len(results) - sum(counts.values()),
        )
    )


def _print_sources(citations: list[dict]) -> None:
    table = Table(title=msg.SOURCES, show_lines=False)
    table.add_column("#", justify="right")
    table.add_column("Documento")
    table.add_column("Sección")
    table.add_column("Similitud", justify="right")
    for c in citations:
        warn = " ⚠️" if c["suspicious"] else ""
        table.add_row(
            f"[{c['n']}]", c["source_path"] + warn, c["heading"] or "—", f"{c['score']:.2f}"
        )
    console.print(table)


@app.command()
def ask(question: Annotated[str, typer.Argument(help="Tu pregunta")]) -> None:
    """Pregunta algo sobre tus documentos. Responde citando las fuentes."""
    with console.status(msg.THINKING):
        result = _request("POST", "/ask", json={"question": question})
    console.print(Markdown(result["answer"]))
    if result["citations"]:
        console.print()
        _print_sources(result["citations"])
    if result["facts_used"]:
        console.print(f"[dim]{msg.FACTS_USED.format(facts='; '.join(result['facts_used']))}[/]")


@app.command()
def search(query: Annotated[str, typer.Argument(help="Texto a buscar")], k: int = 5) -> None:
    """Búsqueda semántica en tus documentos (sin generar respuesta)."""
    results = _request("GET", "/memory/search", params={"q": query, "k": k})["results"]
    if not results:
        console.print(msg.NO_RESULTS)
        return
    _print_sources(results)
    for c in results:
        console.print(f"\n[bold][{c['n']}][/] [dim]{c['source_path']}[/]\n{c['text'][:300]}…")


@app.command()
def remember(text: Annotated[str, typer.Argument(help="Algo sobre ti que deba recordar")]) -> None:
    """Enséñale algo sobre ti. Nemotron extrae los hechos y los guarda sin duplicar."""
    with console.status("Analizando…"):
        facts = _request("POST", "/memory/learn", json={"text": text})["facts"]
    if not facts:
        console.print(msg.NO_FACTS_FOUND)
    for f in facts:
        template = msg.FACT_CREATED if f["created"] else msg.FACT_UPDATED
        console.print(template.format(fact=f["fact"], id=f["id"][:8]))


@memory_app.command("facts")
def list_facts() -> None:
    """Lista lo que el asistente recuerda sobre ti."""
    facts = _request("GET", "/memory/facts")["facts"]
    if not facts:
        console.print(msg.NO_FACTS)
        return
    table = Table(title="Lo que recuerdo sobre ti")
    table.add_column("id")
    table.add_column("Hecho")
    table.add_column("Categoría")
    for f in facts:
        table.add_row(f["id"], f["fact"], f.get("category", ""))
    console.print(table)


@memory_app.command("forget")
def forget(fact_id: Annotated[str, typer.Argument(help="id completo del hecho")]) -> None:
    """Borra un hecho de la memoria (borrado físico en Qdrant)."""
    _request("DELETE", f"/memory/facts/{fact_id}")
    console.print(msg.FACT_FORGOTTEN.format(id=fact_id))


@memory_app.command("docs")
def list_docs() -> None:
    """Lista los documentos indexados."""
    docs = _request("GET", "/documents")["documents"]
    if not docs:
        console.print(msg.NO_DOCUMENTS)
        return
    table = Table(title="Documentos indexados")
    table.add_column("Documento")
    table.add_column("Título")
    table.add_column("Fragmentos", justify="right")
    for d in docs:
        table.add_row(d["source_path"], d.get("title") or "", str(d["chunks"]))
    console.print(table)


@memory_app.command("delete-doc")
def delete_doc(
    source_path: Annotated[str, typer.Argument(help="Ruta tal como aparece en 'docs'")],
) -> None:
    """Elimina un documento y todos sus fragmentos de la memoria."""
    result = _request("DELETE", "/documents", params={"source_path": source_path})
    console.print(msg.DOCUMENT_DELETED.format(path=source_path, chunks=result["removed_chunks"]))
