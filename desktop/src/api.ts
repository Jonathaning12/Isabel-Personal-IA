// Client for the local assistant API. Inside Electron every call goes through the
// preload bridge (window.assistant); in a plain browser (npm run preview) it falls back
// to fetch("/api/...") through the Vite proxy, so the UI can be tested without Electron.

export interface Citation {
  n: number;
  source_path: string;
  title: string | null;
  heading: string | null;
  text: string;
  score: number;
  suspicious: boolean;
}

export interface Action {
  tool: string;
  args: Record<string, unknown>;
  decision: "approve" | "reject" | "stale" | null;
  result: Record<string, unknown>;
}

export interface PendingAction {
  kind?: "client_action";
  tool_call_id: string;
  tool: string;
  args: Record<string, unknown>;
  limits?: Record<string, unknown>;
  program?: string;
  description?: string;
  /** write_note: the note as it is now (exists, size, current content preview). */
  note?: { exists: boolean; chars?: number; current?: string };
  /** git_commit / git_push: what the action touches. */
  git?: { repo: string; branch: string; upstream?: string | null; uncommitted_changes?: string[]; unpushed_commits?: string[] };
  /** create_folder: where the folder goes. */
  folder?: { root: string; path: string };
}

export interface ChatResponse {
  thread_id: string;
  /** client_action: the agent asks the desktop app to act on the computer (e.g. Spotify). */
  status: "done" | "confirm_required" | "client_action";
  answer?: string;
  pending?: PendingAction;
  actions: Action[];
  citations: Citation[];
}

export interface DocumentInfo {
  source_path: string;
  title: string;
  chunks: number;
}

export interface Fact {
  id: string;
  fact: string;
  category: string;
}

export interface Skill {
  name: string;
  description: string;
  parameters: string[];
  runs: number;
}

export interface ProjectsInfo {
  configured: boolean;
  name?: string;
  github?: boolean;
  folders?: string[];
  repos?: string[];
}

export interface VaultInfo {
  configured: boolean;
  name?: string;
  notes?: number;
}

/** Vault notes are indexed as "obsidian/<path in the vault>". */
export const VAULT_PREFIX = "obsidian/";

export interface IngestResult {
  source_path: string;
  status: "indexed" | "unchanged" | "skipped" | "error";
  chunks: number;
  message: string;
}

interface BridgeResult<T> {
  ok: boolean;
  status: number;
  data: T & { detail?: unknown };
}

interface Bridge {
  request<T>(method: string, route: string, body?: unknown): Promise<BridgeResult<T>>;
  pickAndIngest(): Promise<BridgeResult<{ results: IngestResult[] }>>;
  transcribe(wav: ArrayBuffer): Promise<BridgeResult<{ text: string }>>;
  speak(text: string, voice: string | null): Promise<BridgeResult<{ audio: Uint8Array }>>;
  loadSettings(): Promise<unknown>;
  saveSettings(settings: unknown): Promise<boolean>;
  windowInfo(): Promise<{ customControls: boolean; material: "glass" | "acrylic" } | null>;
  windowControl(action: "minimize" | "maximize" | "close"): Promise<boolean>;
  wakeModel(): Promise<{ url: string } | null>;
  openInObsidian(vault: string, file: string): Promise<boolean>;
  runAction(
    tool: string,
    args: Record<string, unknown>,
    threadId: string,
    toolCallId: string,
  ): Promise<Record<string, unknown>>;
  onReminder(callback: (reminder: { text: string }) => void): () => void;
  spotifyStatus(): Promise<{ connected: boolean; clientId: string } | null>;
  spotifyConnect(clientId: string): Promise<{ ok: boolean; error?: string }>;
  spotifyDisconnect(): Promise<{ ok: boolean }>;
  relaunch(): Promise<boolean>;
}

declare global {
  interface Window {
    assistant?: Bridge;
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const bridge = (): Bridge | undefined => window.assistant;

/** The user's clock, sent with every message: the API runs in UTC and answers the time
 *  ("¿qué hora es?") from this, without running any code. */
function localClock(): { local_time: string; timezone: string } {
  const now = new Date();
  const pad = (n: number) => String(Math.abs(n)).padStart(2, "0");
  const offset = -now.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const local =
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}` +
    `${sign}${pad(Math.trunc(offset / 60))}:${pad(offset % 60)}`;
  return { local_time: local, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone };
}
export const isDesktop = () => bridge() !== undefined;

/** Spanish message for the user from an HTTP status and API detail. */
function errorMessage(status: number, detail: unknown): string {
  if (status === 0 || detail === "api_unreachable") {
    return "No puedo conectar con el asistente. ¿Está corriendo `docker compose up -d`?";
  }
  // Backend details are in English (logs/API); the user always gets Spanish.
  if (status === 403) return "La app no tiene permiso para esa acción.";
  if (status === 503) return "El proveedor de IA no responde. Inténtalo de nuevo en un momento.";
  if (status === 409) {
    return typeof detail === "string" && detail.startsWith("There is no action")
      ? "Esa acción ya no está pendiente."
      : "Hay una acción esperando tu aprobación.";
  }
  if (status === 501) return "La voz necesita LLM_PROVIDER=gemini en .env.";
  if (status === 413) return "El archivo es demasiado grande.";
  if (status === 400) return "La petición no es válida (¿audio vacío?).";
  if (status === 422) return "El asistente no aceptó los datos enviados.";
  return `Error ${status} del asistente.`;
}

async function unwrap<T>(pending: Promise<BridgeResult<T>>): Promise<T> {
  const result = await pending;
  if (!result.ok) throw new ApiError(result.status, errorMessage(result.status, result.data?.detail));
  return result.data;
}

async function browserRequest<T>(method: string, route: string, body?: unknown): Promise<BridgeResult<T>> {
  try {
    const response = await fetch(`/api${route}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await response.text();
    let data: T & { detail?: unknown };
    try {
      data = text ? JSON.parse(text) : ({} as T);
    } catch {
      data = { detail: text } as T & { detail?: unknown };
    }
    return { ok: response.ok, status: response.status, data };
  } catch {
    return { ok: false, status: 0, data: { detail: "api_unreachable" } as T & { detail?: unknown } };
  }
}

function request<T>(method: string, route: string, body?: unknown): Promise<T> {
  const b = bridge();
  return unwrap(b ? b.request<T>(method, route, body) : browserRequest<T>(method, route, body));
}

export const api = {
  health: () => request<{ status: string; models: { llm: string; embeddings: string } }>("GET", "/health"),
  chat: (message: string, threadId: string | null, project: string | null) =>
    request<ChatResponse>("POST", "/chat", { message, thread_id: threadId, project, ...localClock() }),
  projects: () => request<ProjectsInfo>("GET", "/projects"),
  confirm: (threadId: string, decision: "approve" | "reject") =>
    request<ChatResponse>("POST", `/chat/${threadId}/confirm`, { decision }),
  clientResult: (threadId: string, toolCallId: string, result: Record<string, unknown>) =>
    request<ChatResponse>("POST", `/chat/${threadId}/client-result`, { tool_call_id: toolCallId, result }),
  documents: () => request<{ documents: DocumentInfo[] }>("GET", "/documents"),
  deleteDocument: (sourcePath: string) =>
    request("DELETE", `/documents?source_path=${encodeURIComponent(sourcePath)}`),
  facts: () => request<{ facts: Fact[] }>("GET", "/memory/facts"),
  deleteFact: (id: string) => request("DELETE", `/memory/facts/${id}`),
  skills: () => request<{ skills: Skill[] }>("GET", "/skills"),
  deleteSkill: (name: string) => request("DELETE", `/skills/${name}`),
  vault: () => request<VaultInfo>("GET", "/vault"),
  syncVault: () => request<{ results: IngestResult[]; removed: number }>("POST", "/vault/sync"),

  async ingest(): Promise<IngestResult[]> {
    const b = bridge();
    if (!b) throw new ApiError(0, "Añadir notas solo está disponible en la app de escritorio.");
    return (await unwrap(b.pickAndIngest())).results;
  },

  /** Natural voice for an answer (WAV bytes). Throws if unavailable: the caller falls back. */
  async speech(text: string, voice: string | null): Promise<ArrayBuffer> {
    const b = bridge();
    if (b) {
      const { audio } = await unwrap(b.speak(text, voice));
      return audio.slice().buffer;
    }
    const response = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice }),
    });
    if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, null));
    return response.arrayBuffer();
  },

  async transcribe(wav: ArrayBuffer): Promise<string> {
    const b = bridge();
    if (b) return (await unwrap(b.transcribe(wav))).text;
    const form = new FormData();
    form.append("audio", new Blob([wav], { type: "audio/wav" }), "voz.wav");
    try {
      const response = await fetch("/api/transcribe", { method: "POST", body: form });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, data.detail));
      return data.text ?? "";
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, errorMessage(0, "api_unreachable"));
    }
  },
};
