// Pure time helpers for reminders and the morning greeting (no Electron here, so they can
// be unit tested with vitest).

// A reminder fires `headsUp` minutes before its time ("ya casi son las 7").
const fireTime = (reminder) => reminder.at - (reminder.headsUp ?? 0) * 60_000;

/** The next time a repeating reminder is due, strictly after `now` (missed ones are skipped). */
function nextOccurrence(at, repeat, now) {
  const next = new Date(at);
  do {
    next.setDate(next.getDate() + (repeat === "weekly" ? 7 : 1));
    while (repeat === "weekdays" && (next.getDay() === 0 || next.getDay() === 6)) next.setDate(next.getDate() + 1);
  } while (next.getTime() <= now);
  return next.getTime();
}

const dayKey = (date) => `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;

const toMinutes = (hhmm) => {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm ?? ""));
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
};

const toClock = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;

/** The usual start of the day: median of the recorded start times (needs 3 days). */
function learnedStart(starts) {
  const minutes = starts.map(toMinutes).filter((m) => m !== null).sort((a, b) => a - b);
  return minutes.length >= 3 ? minutes[Math.floor(minutes.length / 2)] : null;
}

const DAY_STARTS_AT = 4 * 60; // activity before 4:00 belongs to the previous night
const MORNING_ENDS_AT = 12 * 60;

/** Minute of the day from which today's greeting is due (null: no valid time). */
function morningTarget(morning, learned) {
  if (morning.mode === "fixed") return toMinutes(morning.time);
  return learned !== null ? Math.max(DAY_STARTS_AT, learned - 30) : DAY_STARTS_AT;
}

/** Is the greeting due now? (once a day, from the target until noon) */
function morningDue(morning, learned, minutes, today) {
  const target = morningTarget(morning, learned);
  return Boolean(morning.enabled) && morning.lastGreeted !== today && target !== null && minutes >= target && minutes < MORNING_ENDS_AT;
}

module.exports = { fireTime, nextOccurrence, dayKey, toMinutes, toClock, learnedStart, morningTarget, morningDue, DAY_STARTS_AT };
