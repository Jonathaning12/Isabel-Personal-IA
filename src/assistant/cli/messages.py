"""User-facing CLI strings (Spanish), kept in one place for consistency."""

API_UNREACHABLE = (
    "[red]✘ No se pudo conectar con la API en {url}.[/]\n"
    "  Arráncala con: [bold]docker compose up -d[/] "
    "(o en desarrollo: [bold]uv run uvicorn assistant.api.main:app --reload[/])"
)
API_ERROR = "[red]✘ La API respondió con un error {status}:[/] {detail}"
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
