"""Terminal interface (Typer + Rich). It talks to the local FastAPI backend over HTTP.

Commands: chat, ingest, ask, search, remember, memory (facts / docs / forget / delete-doc),
skills (list / show / delete), doctor.
"""

import os
import re
import uuid
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from assistant.cli import messages as msg
from assistant.ingest.loaders import SUPPORTED_EXTENSIONS

app = typer.Typer(help="Asistente personal de IA privado.", no_args_is_help=True)
memory_app = typer.Typer(help="Ver y gestionar la memoria del asistente.", no_args_is_help=True)
app.add_typer(memory_app, name="memory")
skills_app = typer.Typer(
    help="Tus skills reutilizables (programas guardados).", no_args_is_help=True
)
app.add_typer(skills_app, name="skills")
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
        try:
            detail = response.json().get("detail", "")
        except ValueError:  # not JSON (e.g. a plain "Internal Server Error")
            detail = response.text[:200]
        if response.status_code == 503 and detail == "nebius_unavailable":
            console.print(msg.NEBIUS_UNAVAILABLE)
        else:
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


# --- chat with the agent -----------------------------------------------------


def _confirm(pending: dict) -> str:
    """Show exactly what the agent wants to do and ask the user. Returns approve/reject."""
    tool, args = pending["tool"], pending["args"]
    title = msg.CONFIRM_TITLES.get(tool, tool)
    if tool == "run_code_in_sandbox":
        body: Any = Group(
            Text(args.get("explanation") or "", style="bold"),
            Syntax(args["code"], "python", line_numbers=True, word_wrap=True),
            Text(msg.CONFIRM_LIMITS.format(**pending["limits"]), style="dim"),
        )
    elif tool == "run_skill":
        params = ", ".join(f"{k}={v!r}" for k, v in args["params"].items()) or "—"
        body = Group(
            Text(f"Skill «{args['name']}»: {pending.get('description', '')}", style="bold"),
            Text(msg.CONFIRM_PARAMS.format(params=params)),
            Syntax(pending["program"], "python", line_numbers=True, word_wrap=True),
            Text(msg.CONFIRM_LIMITS.format(**pending["limits"]), style="dim"),
        )
    elif tool == "save_skill":
        body = Group(
            Text(f"«{args['name']}»: {args['description']}", style="bold"),
            Text(msg.CONFIRM_PARAMS.format(params=", ".join(args["parameters"]) or "—")),
            Syntax(args["code"], "python", line_numbers=True, word_wrap=True),
        )
    elif tool == "delete_skill":
        body = Text(f"Skill «{args['name']}»")
    elif tool == "remember_fact":
        body = Text(args["fact"])
    else:
        body = Text(str(args))
    console.print(Panel(body, title=title, border_style="yellow"))
    choice = Prompt.ask(msg.CONFIRM_QUESTION, choices=["a", "r"], show_choices=False)
    console.print(msg.APPROVED if choice == "a" else msg.REJECTED)
    return "approve" if choice == "a" else "reject"


def _print_actions(actions: list[dict]) -> None:
    for action in actions:
        result = action["result"]
        if action["decision"] == "reject":
            continue  # already reported when the user rejected it
        if action["decision"] == "stale":
            console.print(msg.ACTION_STALE)
        elif action["tool"] in ("run_code_in_sandbox", "run_skill") and "exit_code" in result:
            output = (result["stdout"] or "") + (result["stderr"] if result["exit_code"] else "")
            title = (
                msg.SANDBOX_TIMEOUT
                if result["timed_out"]
                else msg.SANDBOX_OUTPUT.format(
                    exit_code=result["exit_code"], seconds=result["duration_ms"] / 1000
                )
            )
            style = "green" if result["exit_code"] == 0 else "red"
            console.print(Panel(output.rstrip() or "(sin salida)", title=title, border_style=style))
        elif action["tool"] == "remember_fact" and result.get("status") == "saved":
            console.print(msg.FACT_SAVED.format(fact=result["fact"]))
        elif action["tool"] == "forget_fact" and result.get("status") == "deleted":
            console.print(msg.FACT_DELETED)
        elif action["tool"] == "save_skill" and result.get("status") in ("saved", "updated"):
            console.print(msg.SKILL_SAVED.format(name=result["name"]))
        elif action["tool"] == "delete_skill" and result.get("status") == "deleted":
            console.print(msg.SKILL_DELETED.format(name=action["args"]["name"]))


def _cited(answer: str, citations: list[dict]) -> list[dict]:
    """Only the sources the answer actually cites, e.g. [1] or [3]."""
    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    return [c for c in citations if c["n"] in numbers]


def _chat_turn(thread_id: str, message: str) -> None:
    with console.status(msg.CHAT_THINKING):
        result = _request(
            "POST", "/chat", json={"message": message, "thread_id": thread_id}, timeout=300
        )
    while result["status"] == "confirm_required":
        decision = _confirm(result["pending"])
        with console.status(msg.CHAT_THINKING):
            result = _request(
                "POST", f"/chat/{thread_id}/confirm", json={"decision": decision}, timeout=300
            )
    _print_actions(result["actions"])
    console.print(Markdown(result["answer"]))
    sources = _cited(result["answer"], result["citations"])
    if sources:
        _print_sources(sources)


@app.command()
def chat(
    thread: Annotated[str | None, typer.Option(help="id de una conversación anterior")] = None,
) -> None:
    """Conversa con el agente: busca en tus notas, recuerda y ejecuta código (con permiso)."""
    thread_id = thread or uuid.uuid4().hex[:12]
    console.print(Panel(msg.CHAT_WELCOME.format(thread=thread_id), border_style="cyan"))
    while True:
        try:
            message = Prompt.ask(msg.CHAT_PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if message.lower() in {"/salir", "salir", "exit", "quit"}:
            break
        if not message:
            continue
        try:
            _chat_turn(thread_id, message)
        except typer.Exit:
            continue  # the error was already printed; keep the conversation going
        except httpx.TimeoutException:
            console.print(msg.CHAT_TIMEOUT)
        except Exception as exc:  # never lose the conversation because of one bad turn
            console.print(msg.CHAT_UNEXPECTED.format(error=type(exc).__name__))
    console.print(msg.CHAT_RESUME.format(thread=thread_id))


@app.command()
def doctor() -> None:
    """Comprueba que todo está listo: .env, Nebius, modelos, Qdrant, sandbox y API."""
    from assistant.cli.doctor import run_doctor

    if run_doctor(console):
        console.print(msg.DOCTOR_OK)
    else:
        console.print(msg.DOCTOR_FAIL)
        raise typer.Exit(1)


@skills_app.command("list")
def skills_list() -> None:
    """Lista tus skills guardadas."""
    skills = _request("GET", "/skills")["skills"]
    if not skills:
        console.print(msg.NO_SKILLS)
        return
    table = Table(title="Tus skills")
    table.add_column("Nombre")
    table.add_column("Qué hace")
    table.add_column("Parámetros")
    table.add_column("Usos", justify="right")
    for s in skills:
        table.add_row(
            s["name"], s["description"], ", ".join(s["parameters"]) or "—", str(s["runs"])
        )
    console.print(table)


@skills_app.command("show")
def skills_show(name: Annotated[str, typer.Argument(help="Nombre de la skill")]) -> None:
    """Muestra el código de una skill."""
    s = _request("GET", f"/skills/{name}")
    console.print(
        Panel(
            Group(
                Text(s["description"], style="bold"),
                Text(msg.CONFIRM_PARAMS.format(params=", ".join(s["parameters"]) or "—")),
                Syntax(s["code"], "python", line_numbers=True, word_wrap=True),
            ),
            title=f"Skill «{s['name']}»",
            border_style="cyan",
        )
    )


@skills_app.command("delete")
def skills_delete(name: Annotated[str, typer.Argument(help="Nombre de la skill")]) -> None:
    """Borra una skill."""
    _request("DELETE", f"/skills/{name}")
    console.print(msg.SKILL_DELETED.format(name=name))
