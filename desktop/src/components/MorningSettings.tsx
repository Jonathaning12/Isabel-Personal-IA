import { useEffect, useState } from "react";
import type { MorningSettings as Morning } from "../api";

/** "Buenos días automáticos": when Isabel greets the user with the briefing on her own.
 * The setting lives in the main process (it runs the schedule), not in settings.json. */
export function MorningSettings() {
  const [morning, setMorning] = useState<Morning | null>(null);

  useEffect(() => {
    void window.assistant?.morningSettings().then(setMorning);
  }, []);

  if (!morning) return null;

  const save = async (next: Morning) => {
    setMorning(next);
    const saved = await window.assistant?.setMorning({ enabled: next.enabled, mode: next.mode, time: next.time });
    if (saved?.status === "ok") setMorning({ enabled: saved.enabled, mode: saved.mode, time: saved.time, learned: saved.learned });
  };

  return (
    <>
      <label className="toggle">
        <input type="checkbox" checked={morning.enabled} onChange={(e) => void save({ ...morning, enabled: e.target.checked })} />
        <span>Buenos días automáticos</span>
      </label>
      {morning.enabled ? (
        <>
          <label className="control">
            <span className="control__label">Cuándo</span>
            <select
              value={morning.mode}
              onChange={(e) => {
                const mode = e.target.value === "fixed" ? "fixed" : "auto";
                void save({ ...morning, mode, time: morning.time ?? morning.learned ?? "07:00" });
              }}
            >
              <option value="auto">Al empezar a usar la PC (aprende tu hora)</option>
              <option value="fixed">A una hora fija</option>
            </select>
          </label>
          {morning.mode === "fixed" ? (
            <label className="control">
              <span className="control__label">Hora</span>
              <input
                className="text-input"
                type="time"
                value={morning.time ?? "07:00"}
                onChange={(e) => e.target.value && void save({ ...morning, time: e.target.value })}
              />
            </label>
          ) : null}
          <p className="hint">
            {morning.learned ? `Sueles empezar el día a las ${morning.learned}. ` : "Todavía estoy aprendiendo a qué hora empiezas el día. "}
            Una vez al día, antes de las 12, con la PC en uso. También puedes decirle «me despierto a las 7».
          </p>
        </>
      ) : null}
    </>
  );
}
