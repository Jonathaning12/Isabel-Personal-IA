"""User-facing CLI strings (Spanish), kept in one place for consistency."""

API_UNREACHABLE = (
    "[red]✘ No se pudo conectar con la API en {url}.[/]\n"
    "  Arráncala con: [bold]docker compose up -d[/] "
    "(o en desarrollo: [bold]uv run uvicorn assistant.api.main:app --reload[/])"
)
API_ERROR = "[red]✘ La API respondió con un error {status}:[/] {detail}"
NEBIUS_UNAVAILABLE = (
    "[yellow]⚠ Nebius (el servicio de IA) no respondió a tiempo. "
    "Espera unos segundos y vuelve a intentarlo.[/]"
)
NO_FILES = "[yellow]No encontré archivos compatibles (.md, .txt, .pdf) en esas rutas.[/]"
INGEST_TITLE = "Ingesta de documentos"
INGEST_SUMMARY = (
    "[green]✔[/] Indexados: {indexed} · Sin cambios: {unchanged} · Omitidos/errores: {other}"
)
STATUS_LABELS = {
    "indexed": "[green]indexado[/]",
    "unchanged": "[dim]sin cambios[/]",
    "skipped": "[yellow]omitido[/]",
    "error": "[red]error[/]",
}
THINKING = "Buscando en tus documentos y pensando…"
SOURCES = "Fuentes"
FACTS_USED = "Hechos sobre ti que usé: {facts}"
NO_RESULTS = "[yellow]Sin resultados por encima del umbral de similitud.[/]"
FACT_CREATED = "[green]✔ Recordaré:[/] {fact}  [dim](id {id})[/]"
FACT_UPDATED = "[cyan]↻ Ya lo sabía, lo actualicé:[/] {fact}  [dim](id {id})[/]"
NO_FACTS_FOUND = "[yellow]No encontré hechos duraderos que recordar en ese texto.[/]"
NO_FACTS = "[dim]Todavía no recuerdo nada sobre ti.[/]"
FACT_FORGOTTEN = "[green]✔ Olvidado:[/] {id}"
NO_DOCUMENTS = "[dim]Todavía no hay documentos indexados.[/]"
DOCUMENT_DELETED = "[green]✔ Documento eliminado:[/] {path} ({chunks} fragmentos)"

# --- chat ---------------------------------------------------------------------
CHAT_WELCOME = (
    "[bold]Asistente personal[/] · Nemotron 3 Super en Nebius · memoria local\n"
    "[dim]Conversación {thread} · escribe [bold]/salir[/] para terminar[/]"
)
CHAT_RESUME = "[dim]Para retomarla: assistant chat --thread {thread}[/]"
CHAT_PROMPT = "[bold cyan]Tú[/]"
CHAT_THINKING = "Pensando…"
CHAT_TIMEOUT = "[red]✘ La respuesta tardó demasiado. Inténtalo de nuevo.[/]"
CHAT_UNEXPECTED = "[red]✘ Error inesperado ({error}). La conversación sigue abierta.[/]"
CONFIRM_TITLES = {
    "run_code_in_sandbox": "⚠️  El asistente quiere ejecutar este código",
    "remember_fact": "⚠️  El asistente quiere guardar esto en tu memoria",
    "forget_fact": "⚠️  El asistente quiere borrar este recuerdo",
}
CONFIRM_LIMITS = (
    "Sandbox aislado · sin internet · sin acceso a tus archivos · "
    "memoria {memory} · {cpus} CPU · máx. {timeout_s} s"
)
CONFIRM_QUESTION = "¿Lo apruebas? [bold]a[/]probar / [bold]r[/]echazar"
APPROVED = "[green]✔ Aprobado[/]"
REJECTED = "[yellow]✘ Rechazado: no se ejecutó nada[/]"
SANDBOX_OUTPUT = "Salida del sandbox · código {exit_code} · {seconds:.1f} s"
SANDBOX_TIMEOUT = "Salida del sandbox · ⏱ cortado por tiempo"
FACT_SAVED = "[green]✔ Guardado en memoria:[/] {fact}"
FACT_DELETED = "[green]✔ Recuerdo borrado[/]"
