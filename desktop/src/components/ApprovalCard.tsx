import { useEffect, useRef } from "react";
import type { PendingAction } from "../api";
import { toolLabel } from "../lib/labels";

interface Props {
  pending: PendingAction;
  onDecide: (decision: "approve" | "reject") => void;
  /** True while the local listener waits for a spoken "sí" / "no". */
  voiceConfirm?: boolean;
}

const EFFECTS: Record<string, string> = {
  remember_fact: "Guardará este dato en tu memoria local.",
  forget_fact: "Borrará este dato de tu memoria.",
  run_code_in_sandbox: "Ejecutará este programa en un contenedor aislado.",
  save_skill: "Guardará este programa como skill reutilizable.",
  run_skill: "Ejecutará esta skill en un contenedor aislado.",
  delete_skill: "Borrará esta skill.",
  git_commit: "Añadirá todos los cambios (git add -A) y hará un commit con este mensaje.",
  git_push: "Subirá estos commits al repositorio remoto (GitHub).",
  create_folder: "Creará esta carpeta nueva.",
  save_routine: "Guardará esta rutina (si ya existe una con ese nombre, la reemplaza); después podrás ejecutarla diciendo su nombre.",
  read_clipboard: "Leerá el texto que tienes copiado (puede contener contraseñas o códigos).",
  open_url: "Abrirá esta dirección en tu navegador. Revisa que no lleve datos tuyos.",
  write_clipboard: "Reemplazará lo que tienes copiado por este texto.",
  look_at_screen: "Tomará una captura de tu pantalla y la enviará a Gemini para responder. No se guarda.",
};

const NOTE_EFFECTS: Record<string, string> = {
  create: "Creará esta nota nueva en tu bóveda de Obsidian.",
  append: "Añadirá este texto al final de la nota.",
  overwrite: "Reemplazará la nota completa (se guarda una copia de seguridad de la versión actual).",
};

const MODE_LABELS: Record<string, string> = { create: "Crear", append: "Añadir al final", overwrite: "Reemplazar" };

const ARG_LABELS: Record<string, string> = {
  explanation: "Qué hace",
  fact: "Dato",
  category: "Categoría",
  fact_id: "Id del dato",
  name: "Nombre",
  description: "Descripción",
  parameters: "Parámetros",
  params: "Valores",
  path: "Ruta",
  repo: "Repositorio",
  message: "Mensaje",
  text: "Texto",
  question: "Pregunta",
  steps: "Pasos",
};

/** Routine steps as readable lines ("Abrir una app: Discord"). */
function describeSteps(steps: unknown): string {
  if (!Array.isArray(steps)) return JSON.stringify(steps);
  return steps
    .map((s: { tool?: string; args?: Record<string, unknown> }, i) => {
      const detail = Object.entries(s.args ?? {})
        .filter(([, v]) => v !== "" && v != null)
        .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
        .join(", ");
      return `${i + 1}. ${toolLabel(s.tool ?? "?")}${detail ? ` (${detail})` : ""}`;
    })
    .join("   ");
}

/** Human-in-the-loop: shows exactly what will run, and nothing runs without "Aprobar". */
export function ApprovalCard({ pending, onDecide, voiceConfirm = false }: Props) {
  const reject = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);
  // Focus "Rechazar" first so a stray Enter can never approve by accident.
  useEffect(() => reject.current?.focus(), [pending]);

  // Modal keyboard: Esc rejects, Tab stays inside the card.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onDecide("reject");
        return;
      }
      if (event.key !== "Tab" || !dialog.current) return;
      const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>("button, [tabindex]:not([tabindex='-1'])"));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const inside = dialog.current.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || !inside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !inside)) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDecide]);

  const args = pending.args;
  const isNote = pending.tool === "write_note";
  const mode = String(args.mode ?? "");
  const code = pending.program ?? (typeof args.code === "string" ? args.code : null);
  const limits = pending.limits;
  // Code and note content are shown in their own blocks; empty values add nothing.
  const rows = Object.entries(args)
    .filter(([key, value]) => key !== "code" && key !== "content" && value !== "" && value != null)
    .map(
      ([key, value]) =>
        [key, key === "mode" ? (MODE_LABELS[mode] ?? mode) : key === "steps" ? describeSteps(value) : value] as const,
    );
  const effect = isNote ? NOTE_EFFECTS[mode] : (pending.description ?? EFFECTS[pending.tool] ?? "Acción con efectos.");

  return (
    <div className="approval-backdrop" role="presentation">
      <section ref={dialog} className="approval" role="dialog" aria-modal="true" aria-labelledby="approval-title">
        <p className="eyebrow">Necesito tu aprobación</p>
        <h2 id="approval-title">{toolLabel(pending.tool)}</h2>
        <p className="approval__effect">{effect}</p>

        {rows.length ? (
          <dl className="approval__args">
            {rows.map(([key, value]) => (
              <div key={key}>
                <dt>{ARG_LABELS[key] ?? key}</dt>
                <dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd>
              </div>
            ))}
          </dl>
        ) : null}

        {code ? (
          <pre className="approval__code">
            <code>{code}</code>
          </pre>
        ) : null}

        {isNote ? (
          <>
            <p className="approval__label">{mode === "append" ? "Texto que se añadirá" : "Contenido nuevo"}</p>
            <pre className="approval__code approval__code--note">
              <code>{String(args.content ?? "")}</code>
            </pre>
            {pending.note?.exists ? (
              <details className="approval__current" open={mode === "overwrite"}>
                <summary>
                  Nota actual ({pending.note.chars} caracteres
                  {(pending.note.chars ?? 0) > (pending.note.current?.length ?? 0)
                    ? `; se muestran los primeros ${pending.note.current?.length}`
                    : ""}
                  ){mode === "overwrite" ? " — será reemplazada" : ""}
                </summary>
                <pre className="approval__code">
                  <code>{pending.note.current}</code>
                </pre>
              </details>
            ) : (
              <p className="approval__limits">La nota no existe todavía: se creará.</p>
            )}
          </>
        ) : null}

        {limits ? (
          <p className="approval__limits">
            Sin red · sin acceso a tus archivos · {String(limits.memory)} de memoria · {String(limits.cpus)} CPU ·{" "}
            {String(limits.timeout_s)} s máximo
          </p>
        ) : null}

        {pending.git ? (
          <>
            <p className="approval__label">
              Rama {pending.git.branch}
              {pending.git.upstream ? ` → ${pending.git.upstream}` : ""}
            </p>
            {pending.git.uncommitted_changes ? (
              <pre className="approval__code approval__code--list">
                <code>{pending.git.uncommitted_changes.join("\n") || "Sin cambios"}</code>
              </pre>
            ) : null}
            {pending.git.unpushed_commits ? (
              <pre className="approval__code approval__code--list">
                <code>{pending.git.unpushed_commits.join("\n") || "No hay commits por subir"}</code>
              </pre>
            ) : null}
          </>
        ) : null}

        {pending.folder ? (
          <p className="approval__limits">
            {pending.folder.root} / {pending.folder.path}
          </p>
        ) : null}

        {voiceConfirm ? (
          <p className="approval__voice">
            <span className="approval__voice-dot" /> Escuchando: di «apruebo» o «no»
          </p>
        ) : null}

        <div className="approval__buttons">
          <button ref={reject} type="button" className="button button--ghost" onClick={() => onDecide("reject")}>
            Rechazar <kbd>Esc</kbd>
          </button>
          <button type="button" className="button button--primary" onClick={() => onDecide("approve")}>
            Aprobar
          </button>
        </div>
      </section>
    </div>
  );
}
