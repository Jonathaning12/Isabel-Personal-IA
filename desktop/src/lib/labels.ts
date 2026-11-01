// User-facing Spanish labels for the agent's tools and decisions.

export const TOOL_LABELS: Record<string, string> = {
  search_knowledge: "Buscar en tus notas",
  list_facts: "Revisar tu memoria",
  remember_fact: "Guardar un dato sobre ti",
  forget_fact: "Olvidar un dato",
  run_code_in_sandbox: "Ejecutar código en el sandbox",
  list_skills: "Revisar tus skills",
  save_skill: "Guardar una skill",
  run_skill: "Ejecutar una skill",
  delete_skill: "Borrar una skill",
  list_notes: "Revisar tus notas de Obsidian",
  read_note: "Leer una nota",
  search_notes: "Buscar texto en tus notas",
  list_tasks: "Revisar tus tareas pendientes",
  write_note: "Escribir en una nota de Obsidian",
  list_projects: "Revisar tus proyectos",
  git_status: "Revisar el estado de git",
  git_diff: "Revisar los cambios",
  git_commit: "Hacer commit",
  git_push: "Hacer push a GitHub",
  create_folder: "Crear una carpeta",
  media_control: "Controlar la música",
  now_playing: "Ver qué suena",
  spotify_play: "Poner música en Spotify",
  set_reminder: "Crear un recordatorio",
  set_morning_greeting: "Programar los buenos días",
  calendar_events: "Revisar tu calendario",
  calendar_create_event: "Crear un evento en tu calendario",
  gmail_search: "Revisar tu correo",
  list_reminders: "Revisar tus recordatorios",
  cancel_reminder: "Cancelar un recordatorio",
  open_app: "Abrir una app",
  open_url: "Abrir un sitio web",
  open_folder: "Abrir una carpeta",
  open_file: "Abrir un archivo",
  open_in_editor: "Abrir en VS Code",
  list_routines: "Revisar tus rutinas",
  save_routine: "Guardar una rutina",
  run_routine: "Ejecutar una rutina",
  read_clipboard: "Leer lo que copiaste",
  write_clipboard: "Dejar texto copiado",
  look_at_screen: "Mirar tu pantalla",
  get_weather: "Consultar el clima",
  web_search: "Buscar en internet",
  find_files: "Buscar archivos",
  repos_overview: "Revisar tus repositorios",
};

export const toolLabel = (tool: string) => TOOL_LABELS[tool] ?? tool;

export const DECISION_LABELS: Record<string, string> = {
  approve: "Aprobada",
  reject: "Rechazada",
  stale: "No ejecutada (cambió)",
};

export const STATUS_LABELS: Record<string, string> = {
  idle: "",
  gathering: "Recopilando información",
  thinking: "Pensando",
  speaking: "Hablando",
  listening: "Escuchando",
  transcribing: "Transcribiendo",
  awaiting: "Necesito tu aprobación",
  error: "Algo salió mal",
};

export function timeLabel(date: Date): string {
  return date.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
}
