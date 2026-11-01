import { type ReactNode, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  type DocumentInfo,
  type Episode,
  type Fact,
  type ProjectsInfo,
  type Skill,
  VAULT_PREFIX,
  type VaultInfo,
  api,
  isDesktop,
} from "../api";
import { timeLabel } from "../lib/labels";
import { Markdown } from "../lib/markdown";
import { TidyMemory } from "./TidyMemory";
import type { ActivityItem, Message } from "../useAssistant";
import { BoltIcon, BrainIcon, BranchIcon, ChatIcon, FileIcon, FolderIcon, OpenIcon, PlusIcon, PulseIcon, RefreshIcon, TrashIcon } from "./Icons";

type Tab = "activity" | "chat" | "docs" | "projects" | "memory" | "skills";

const TABS: { id: Tab; label: string; icon: ReactNode }[] = [
  { id: "activity", label: "Actividad", icon: <PulseIcon /> },
  { id: "chat", label: "Conversación", icon: <ChatIcon /> },
  { id: "docs", label: "Documentos", icon: <FileIcon /> },
  { id: "projects", label: "Proyectos", icon: <FolderIcon /> },
  { id: "memory", label: "Memoria", icon: <BrainIcon /> },
  { id: "skills", label: "Skills", icon: <BoltIcon /> },
];

interface Props {
  open: boolean;
  vault: VaultInfo | null;
  onVaultChanged: () => void;
  currentProject: string | null;
  onSelectProject: (project: string | null) => void;
  activity: ActivityItem[];
  messages: Message[];
  refreshKey: number;
  onNewConversation: () => void;
  onLog: (item: Omit<ActivityItem, "id" | "at">) => void;
  onNotice: (text: string) => void;
}

/** Collapsible panel with everything the agent works with: activity, notes, memory, skills. */
export function Sidebar({ open, vault, onVaultChanged, currentProject, onSelectProject, activity, messages, refreshKey, onNewConversation, onLog, onNotice }: Props) {
  const [syncing, setSyncing] = useState(false);
  const [tab, setTab] = useState<Tab>("activity");
  const [docs, setDocs] = useState<DocumentInfo[] | null>(null);
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [habits, setHabits] = useState<{ name: string; plays: number }[]>([]);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [projects, setProjects] = useState<ProjectsInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);

  const report = useCallback((error: unknown) => onNotice(error instanceof ApiError ? error.message : "Error inesperado."), [onNotice]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [d, f, s, p, h, e] = await Promise.all([
        api.documents(),
        api.facts(),
        api.skills(),
        api.projects().catch(() => ({ configured: false }) as ProjectsInfo),
        api.habits().catch(() => ({ artists: [] })),
        api.episodes().catch(() => ({ episodes: [] as Episode[] })),
      ]);
      setDocs(d.documents);
      setFacts(f.facts);
      setHabits(h.artists);
      setEpisodes(e.episodes);
      setSkills(s.skills);
      setProjects(p);
    } catch (error) {
      report(error);
    } finally {
      setLoading(false);
    }
  }, [report]);

  useEffect(() => {
    if (open) void refresh();
  }, [open, refreshKey, refresh]);

  // Deleting needs a second click on the same item: no accidental data loss.
  const remove = async (key: string, action: () => Promise<unknown>, label: string) => {
    if (confirming !== key) {
      setConfirming(key);
      window.setTimeout(() => setConfirming((c) => (c === key ? null : c)), 3000);
      return;
    }
    setConfirming(null);
    try {
      await action();
      onLog({ kind: "docs", title: label, status: "ok" });
      await refresh();
    } catch (error) {
      report(error);
    }
  };

  const syncVault = async () => {
    setSyncing(true);
    try {
      const { results, removed } = await api.syncVault();
      const indexed = results.filter((r) => r.status === "indexed").length;
      const unchanged = results.filter((r) => r.status === "unchanged").length;
      onLog({
        kind: "docs",
        title: "Obsidian sincronizado",
        detail: `${indexed} actualizada(s) · ${unchanged} sin cambios${removed ? ` · ${removed} quitada(s)` : ""}`,
        status: "ok",
      });
      onVaultChanged();
      await refresh();
    } catch (error) {
      report(error);
    } finally {
      setSyncing(false);
    }
  };

  const ingest = async () => {
    try {
      const results = await api.ingest();
      if (!results.length) return;
      const indexed = results.filter((r) => r.status === "indexed").length;
      const failed = results.filter((r) => r.status === "error" || r.status === "skipped");
      onLog({
        kind: "docs",
        title: `Notas añadidas: ${indexed}`,
        detail: failed.length ? `${failed.length} omitida(s): ${failed.map((r) => r.source_path).join(", ")}` : undefined,
        status: failed.length ? "warn" : "ok",
      });
      await refresh();
    } catch (error) {
      report(error);
    }
  };

  return (
    <aside className={`sidebar ${open ? "sidebar--open" : ""}`} aria-hidden={!open} inert={!open}>
      <nav className="sidebar__tabs" aria-label="Secciones">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tab ${tab === t.id ? "tab--active" : ""}`}
            onClick={() => setTab(t.id)}
            title={t.label}
            aria-label={t.label}
            aria-pressed={tab === t.id}
          >
            {t.icon}
          </button>
        ))}
      </nav>

      <div className="sidebar__content">
        <header className="sidebar__header">
          <h2>{TABS.find((t) => t.id === tab)?.label}</h2>
          {tab === "chat" ? (
            <button type="button" className="icon-button" onClick={onNewConversation} title="Nueva conversación" aria-label="Nueva conversación">
              <PlusIcon />
            </button>
          ) : tab !== "activity" ? (
            <button type="button" className={`icon-button ${loading ? "spin" : ""}`} onClick={() => void refresh()} title="Actualizar" aria-label="Actualizar">
              <RefreshIcon />
            </button>
          ) : null}
        </header>

        {tab === "activity" ? (
          <ul className="list">
            {activity.length === 0 ? <Empty>Aquí verás lo que hace el agente: búsquedas, código, aprobaciones.</Empty> : null}
            {activity.map((item) => (
              <li key={item.id} className={`list__item activity activity--${item.status ?? "ok"}`}>
                <span className="activity__dot" />
                <div>
                  <p className="list__title">{item.title}</p>
                  {item.detail ? <p className="list__detail">{item.detail}</p> : null}
                </div>
                <time className="list__time">{timeLabel(item.at)}</time>
              </li>
            ))}
          </ul>
        ) : null}

        {tab === "chat" ? (
          <ul className="list chat">
            {messages.length === 0 ? <Empty>Todavía no hay mensajes en esta conversación.</Empty> : null}
            {messages.map((m) => (
              <li key={m.id} className={`chat__message chat__message--${m.role}`}>
                {m.role === "assistant" ? <Markdown text={m.text} citations={m.citations} /> : <p>{m.text}</p>}
                <time className="list__time">{timeLabel(m.at)}</time>
              </li>
            ))}
          </ul>
        ) : null}

        {tab === "docs" ? (
          <>
            {vault?.configured ? (
              <div className="vault-card">
                <div>
                  <p className="list__title">Obsidian · {vault.name || "bóveda"}</p>
                  <p className="list__detail">
                    {vault.notes} nota(s) · Isabel puede leerlas; para escribir te pide aprobación
                  </p>
                </div>
                <button type="button" className={`icon-button ${syncing ? "spin" : ""}`} onClick={() => void syncVault()} disabled={syncing} title="Sincronizar con la búsqueda" aria-label="Sincronizar Obsidian">
                  <RefreshIcon />
                </button>
              </div>
            ) : vault ? (
              <p className="list__detail vault-card">Sin bóveda de Obsidian. Define OBSIDIAN_VAULT en .env y reinicia la API.</p>
            ) : null}
            <button type="button" className="button button--ghost button--block" onClick={() => void ingest()} disabled={!isDesktop()}>
              <PlusIcon /> Añadir notas (.md, .txt, .pdf)
            </button>
            <ul className="list">
              {docs?.length === 0 ? <Empty>No hay notas indexadas.</Empty> : null}
              {docs?.map((d) => (
                <li key={d.source_path} className="list__item">
                  <FileIcon className="list__icon" />
                  <div>
                    <p className="list__title">{d.title}</p>
                    <p className="list__detail">
                      {d.source_path} · {d.chunks} fragmento(s)
                    </p>
                  </div>
                  {d.source_path.startsWith(VAULT_PREFIX) && vault?.name ? (
                    <button
                      type="button"
                      className="icon-button"
                      onClick={() => void window.assistant?.openInObsidian(vault.name!, d.source_path.slice(VAULT_PREFIX.length))}
                      title="Abrir en Obsidian"
                      aria-label="Abrir en Obsidian"
                    >
                      <OpenIcon />
                    </button>
                  ) : null}
                  <DeleteButton
                    armed={confirming === `doc:${d.source_path}`}
                    onClick={() => void remove(`doc:${d.source_path}`, () => api.deleteDocument(d.source_path), `Nota borrada: ${d.title}`)}
                  />
                </li>
              ))}
            </ul>
          </>
        ) : null}

        {tab === "projects" ? (
          projects?.configured ? (
            <>
              <p className="list__detail project-hint">
                Elige el proyecto actual: es «esta carpeta» cuando hablas con Isabel (por ejemplo, «revisa si hay
                commits pendientes»). Consultar es libre; commit, push y crear carpetas piden tu aprobación.
                {projects.github ? "" : " Para hacer push a GitHub, añade GITHUB_TOKEN en .env."}
              </p>
              <h3 className="list__section">Repositorios git</h3>
              <ul className="list">
                {projects.repos?.length === 0 ? <Empty>No encontré repositorios git.</Empty> : null}
                {projects.repos?.map((repo) => (
                  <ProjectRow key={repo} name={repo} repo selected={currentProject === repo} onSelect={onSelectProject} />
                ))}
              </ul>
              <h3 className="list__section">Carpetas en {projects.name}</h3>
              <ul className="list">
                {projects.folders
                  ?.filter((f) => !projects.repos?.includes(f))
                  .map((folder) => (
                    <ProjectRow key={folder} name={folder} selected={currentProject === folder} onSelect={onSelectProject} />
                  ))}
              </ul>
            </>
          ) : (
            <p className="list__detail">Sin carpeta de proyectos. Define PROJECTS_HOST en .env y reinicia la API.</p>
          )
        ) : null}

        {tab === "memory" ? (
          <ul className="list">
            {facts && facts.length > 1 ? (
              <li className="list__tidy">
                <TidyMemory onDone={() => void refresh()} onNotice={onNotice} />
              </li>
            ) : null}
            {habits.length ? (
              <>
                <h3 className="list__section">Lo que más escuchas (aprendido)</h3>
                <li className="list__item">
                  <PulseIcon className="list__icon" />
                  <div>
                    <p className="list__title">{habits.slice(0, 5).map((a) => a.name).join(" · ")}</p>
                    <p className="list__detail">Lo uso cuando dices «pon música» sin decir qué.</p>
                  </div>
                  <DeleteButton
                    armed={confirming === "habits"}
                    onClick={() => void remove("habits", () => api.clearHabits(), "Hábitos olvidados")}
                  />
                </li>
              </>
            ) : null}
            {episodes.length ? (
              <>
                <h3 className="list__section">Conversaciones recordadas</h3>
                {episodes.slice(0, 20).map((ep) => (
                  <li key={ep.id} className="list__item">
                    <ChatIcon className="list__icon" />
                    <div>
                      <p className="list__title">{ep.summary}</p>
                      <p className="list__detail">{new Date(ep.ended_at).toLocaleDateString("es")}</p>
                    </div>
                    <DeleteButton
                      armed={confirming === `episode:${ep.id}`}
                      onClick={() => void remove(`episode:${ep.id}`, () => api.deleteEpisode(ep.id), "Conversación olvidada")}
                    />
                  </li>
                ))}
              </>
            ) : null}
            {habits.length || episodes.length ? <h3 className="list__section">Datos sobre ti</h3> : null}
            {facts?.length === 0 ? (
              <Empty>Aún no sé nada de ti. Voy aprendiendo de lo que me cuentas, o dime «recuerda que…».</Empty>
            ) : null}
            {facts?.map((f) => (
              <li key={f.id} className="list__item">
                <BrainIcon className="list__icon" />
                <div>
                  <p className="list__title">{f.fact}</p>
                  <p className="list__detail">
                    {f.category}
                    {f.source === "learned" ? " · aprendido de una conversación" : ""}
                  </p>
                </div>
                <DeleteButton
                  armed={confirming === `fact:${f.id}`}
                  onClick={() => void remove(`fact:${f.id}`, () => api.deleteFact(f.id), "Dato olvidado")}
                />
              </li>
            ))}
          </ul>
        ) : null}

        {tab === "skills" ? (
          <ul className="list">
            {skills?.length === 0 ? <Empty>Sin skills. Pide «guarda esto como skill» tras ejecutar código.</Empty> : null}
            {skills?.map((s) => (
              <li key={s.name} className="list__item">
                <BoltIcon className="list__icon" />
                <div>
                  <p className="list__title">
                    {s.name}({s.parameters.join(", ")})
                  </p>
                  <p className="list__detail">
                    {s.description} · {s.runs} ejecución(es)
                  </p>
                </div>
                <DeleteButton
                  armed={confirming === `skill:${s.name}`}
                  onClick={() => void remove(`skill:${s.name}`, () => api.deleteSkill(s.name), `Skill borrada: ${s.name}`)}
                />
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </aside>
  );
}

function ProjectRow({
  name,
  repo = false,
  selected,
  onSelect,
}: {
  name: string;
  repo?: boolean;
  selected: boolean;
  onSelect: (project: string | null) => void;
}) {
  return (
    <li className={`list__item project ${selected ? "project--selected" : ""}`}>
      {repo ? <BranchIcon className="list__icon" /> : <FolderIcon className="list__icon" />}
      <button type="button" className="project__name" onClick={() => onSelect(selected ? null : name)}>
        {name}
      </button>
      {selected ? <span className="project__badge">actual</span> : null}
    </li>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <li className="list__empty">{children}</li>;
}

function DeleteButton({ armed, onClick }: { armed: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className={`icon-button icon-button--danger ${armed ? "icon-button--armed" : ""}`}
      onClick={onClick}
      title={armed ? "Pulsa otra vez para borrar" : "Borrar"}
      aria-label={armed ? "Confirmar borrado" : "Borrar"}
    >
      <TrashIcon />
    </button>
  );
}
