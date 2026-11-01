import { useState } from "react";
import { ApiError, type ConsolidationPreview, api } from "../api";

/** "Ordenar memoria": Isabel proposes merging duplicates and dropping outdated facts; the
 * user reads the proposal and applies it (or not). Nothing changes before "Aplicar". */
export function TidyMemory({ onDone, onNotice }: { onDone: () => void; onNotice: (text: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState<ConsolidationPreview | null>(null);

  const report = (error: unknown) => onNotice(error instanceof ApiError ? error.message : "Error inesperado.");

  const propose = async () => {
    setBusy(true);
    try {
      const result = await api.consolidate();
      if (!result.plan.merge.length && !result.plan.drop.length) onNotice("Tu memoria ya está ordenada.");
      else setProposal(result);
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!proposal) return;
    setBusy(true);
    try {
      const done = await api.applyConsolidation(proposal.plan);
      onNotice(`Memoria ordenada: ${done.merged} unidos, ${done.dropped} borrados.`);
      setProposal(null);
      onDone();
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  };

  if (!proposal) {
    return (
      <button type="button" className="button button--ghost button--block" onClick={() => void propose()} disabled={busy}>
        {busy ? "Revisando tu memoria…" : "Ordenar memoria"}
      </button>
    );
  }
  return (
    <div className="tidy">
      <p className="list__detail">Esto propongo cambiar:</p>
      <ul className="tidy__changes">
        {proposal.preview.merge.map((m) => (
          <li key={m.into}>
            Unir «{m.from.join("» + «")}» → <strong>{m.into}</strong>
          </li>
        ))}
        {proposal.preview.drop.map((fact) => (
          <li key={fact}>Borrar «{fact}»</li>
        ))}
      </ul>
      <div className="tidy__actions">
        <button type="button" className="button button--primary" onClick={() => void apply()} disabled={busy}>
          Aplicar
        </button>
        <button type="button" className="button button--ghost" onClick={() => setProposal(null)} disabled={busy}>
          Cancelar
        </button>
      </div>
    </div>
  );
}
