// Spoken phrases built by the app itself (not by the model): reminders read aloud.

/** "Jonathan, no te olvides de regar las plantas. Ya casi son las 7 de la tarde." */
export function reminderPhrase(text: string, name: string, soon: Date | null): string {
  const task = text.trim().replace(/[.!]+$/, "");
  const lead = name ? `${name}, no` : "No";
  const remind = /^(no |hoy |ya )/i.test(task) ? `${name ? `${name}, ` : ""}${task}.` : `${lead} te olvides de ${task}.`;
  return soon ? `${remind} Ya casi son ${spokenTime(soon)}.` : remind;
}

/** 19:00 → "las 7 de la tarde"; 13:30 → "la 1 y media de la tarde". */
export function spokenTime(date: Date): string {
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const hour12 = hours % 12 || 12;
  const part = hours < 12 ? "de la mañana" : hours < 20 ? "de la tarde" : "de la noche";
  const extra = minutes === 0 ? "" : minutes === 30 ? " y media" : minutes === 15 ? " y cuarto" : ` y ${minutes}`;
  return `${hour12 === 1 ? "la" : "las"} ${hour12}${extra} ${part}`;
}
