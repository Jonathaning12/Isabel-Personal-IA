// Reminders and the morning greeting: repetition, heads-up and the learned start of the day.
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";
import { reminderPhrase, spokenTime } from "../src/lib/phrases";

const require = createRequire(import.meta.url);
const schedule = require("../electron/schedule.cjs");

const FRIDAY_7PM = new Date(2026, 9, 30, 19, 0).getTime(); // Friday 30 Oct 2026, 19:00
const show = (ms: number) => new Date(ms).toString().slice(0, 21);

describe("nextOccurrence", () => {
  it.each([
    ["daily", "Sat Oct 31 2026 19:00"],
    ["weekdays", "Mon Nov 02 2026 19:00"],
    ["weekly", "Fri Nov 06 2026 19:00"],
  ])("%s → %s", (repeat, expected) => {
    expect(show(schedule.nextOccurrence(FRIDAY_7PM, repeat, FRIDAY_7PM + 60_000))).toBe(expected);
  });

  it("skips the ones missed while the PC was off", () => {
    const threeDaysLater = FRIDAY_7PM + 3 * 86_400_000 + 60_000;
    expect(show(schedule.nextOccurrence(FRIDAY_7PM, "daily", threeDaysLater))).toBe("Tue Nov 03 2026 19:00");
  });

  it("fires heads-up minutes early", () => {
    expect(schedule.fireTime({ at: FRIDAY_7PM, headsUp: 5 })).toBe(FRIDAY_7PM - 5 * 60_000);
  });
});

describe("morning greeting", () => {
  const today = "2026-10-31";

  it("learns the usual start only after three days (median)", () => {
    expect(schedule.learnedStart(["07:10", "07:00"])).toBeNull();
    expect(schedule.learnedStart(["07:10", "07:00", "09:30"])).toBe(7 * 60 + 10);
  });

  it("fixed mode greets from that time until noon, once a day", () => {
    const morning = { enabled: true, mode: "fixed", time: "07:00", lastGreeted: null };
    expect(schedule.morningDue(morning, null, 6 * 60 + 59, today)).toBe(false);
    expect(schedule.morningDue(morning, null, 7 * 60, today)).toBe(true);
    expect(schedule.morningDue(morning, null, 12 * 60, today)).toBe(false);
    expect(schedule.morningDue({ ...morning, lastGreeted: today }, null, 8 * 60, today)).toBe(false);
  });

  it("auto mode waits until half an hour before the learned start", () => {
    const morning = { enabled: true, mode: "auto", time: null, lastGreeted: null };
    expect(schedule.morningDue(morning, 7 * 60, 6 * 60, today)).toBe(false);
    expect(schedule.morningDue(morning, 7 * 60, 6 * 60 + 30, today)).toBe(true);
    expect(schedule.morningDue({ ...morning, enabled: false }, 7 * 60, 8 * 60, today)).toBe(false);
  });
});

describe("reminder phrases", () => {
  it("uses the name and warns before the time", () => {
    expect(reminderPhrase("regar las plantas", "Jonathan", new Date(2026, 9, 31, 19, 0))).toBe(
      "Jonathan, no te olvides de regar las plantas. Ya casi son las 7 de la tarde.",
    );
    expect(reminderPhrase("llamar a mamá.", "", null)).toBe("No te olvides de llamar a mamá.");
  });

  it.each([
    [13, 30, "la 1 y media de la tarde"],
    [8, 15, "las 8 y cuarto de la mañana"],
    [21, 5, "las 9 y 5 de la noche"],
  ])("%i:%i → %s", (h, m, expected) => {
    expect(spokenTime(new Date(2026, 0, 1, h, m))).toBe(expected);
  });
});
