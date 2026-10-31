// Everyday actions on the user's computer, requested by the agent and run here (Electron
// main process): reminders, opening apps / websites / folders / files / projects,
// routines, clipboard and screen questions. Music and Spotify live in computer.cjs.
//
// Safety: apps can only be opened from the Start menu list; websites only over http(s);
// folders and files only inside known user folders or the projects folder; files with
// executable extensions are never opened. Writing the clipboard, saving a routine and
// taking a screenshot are approved by the user in the chat before they reach this file.

const { app, Notification, clipboard, desktopCapturer, powerMonitor, screen, shell } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const fsSync = require("node:fs");
const path = require("node:path");

const MAX_REMINDER_DAYS = 30;
const CHECK_EVERY_MS = 15_000;
const OPENABLE_FILES = new Set([
  "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "txt", "md", "csv", "rtf",
  "png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "mp3", "wav", "flac", "m4a", "mp4", "mkv", "mov",
  "avi", "webm", "zip", "json", "html",
]); // fmt: skip

let config = { apiUrl: "", getWindow: () => null, runMusic: async () => ({}) };

function init(options) {
  config = { ...config, ...options };
}

const userFile = (name) => path.join(app.getPath("userData"), name);

async function readJson(file, fallback) {
  try {
    return JSON.parse(await fs.readFile(userFile(file), "utf-8"));
  } catch {
    return fallback;
  }
}

/** Write to a temp file, then rename: a crash mid-write never leaves a broken file. */
async function writeJson(file, value) {
  const target = userFile(file);
  const temp = `${target}.${process.pid}.tmp`;
  await fs.writeFile(temp, JSON.stringify(value, null, 2), "utf-8");
  await fs.rename(temp, target);
}

// Every read-modify-write of a store runs one after another, never interleaved (a reminder
// set while another one fires must not be lost or fire twice).
let queue = Promise.resolve();
function serial(task) {
  const run = queue.then(task, task);
  queue = run.catch(() => undefined);
  return run;
}

const normalize = (text) =>
  String(text).toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, " ").trim();

// ---- reminders ------------------------------------------------------------------------

function showWindow() {
  const window = config.getWindow();
  if (!window) return;
  if (window.isMinimized()) window.restore();
  window.show();
  window.focus();
}

const REPEATS = new Set(["none", "daily", "weekdays", "weekly"]);
// A reminder fires `headsUp` minutes before its time ("ya casi son las 7").
const fireTime = (r) => r.at - (r.headsUp ?? 0) * 60_000;

/** The next time a repeating reminder is due, strictly after `now` (missed ones are skipped). */
function nextOccurrence(at, repeat, now) {
  const next = new Date(at);
  do {
    next.setDate(next.getDate() + (repeat === "weekly" ? 7 : 1));
    while (repeat === "weekdays" && (next.getDay() === 0 || next.getDay() === 6)) next.setDate(next.getDate() + 1);
  } while (next.getTime() <= now);
  return next.getTime();
}

async function fireDueReminders() {
  const due = await serial(async () => {
    const reminders = await readJson("reminders.json", []);
    const now = Date.now();
    const ready = reminders.filter((r) => fireTime(r) <= now);
    if (!ready.length) return [];
    const kept = reminders
      .map((r) => (fireTime(r) > now ? r : r.repeat && r.repeat !== "none" ? { ...r, at: nextOccurrence(r.at, r.repeat, now) } : null))
      .filter(Boolean)
      .sort((a, b) => fireTime(a) - fireTime(b));
    await writeJson("reminders.json", kept);
    return ready;
  });
  for (const reminder of due) {
    if (Notification.isSupported()) {
      const notification = new Notification({ title: "Isabel · Recordatorio", body: reminder.text, silent: false });
      notification.on("click", showWindow);
      notification.show();
    }
    // The page says it aloud and shows it (works even with the window in the tray).
    config.getWindow()?.webContents.send("reminder", { text: reminder.text, at: reminder.at, early: (reminder.headsUp ?? 0) > 0 });
    config.getWindow()?.flashFrame(true);
  }
}

// ---- morning greeting -----------------------------------------------------------------
// Isabel says "buenos días" with the briefing without being asked, once a day:
// - "fixed": at the chosen time (or at the first moment the user is at the PC after it);
// - "auto": when the user first uses the PC in the morning. The time they usually start
//   (median of the last 14 days) is learned, so an early boot does not trigger it.
// Only while the PC is in use (not locked or idle) and before noon.
const MORNING_FILE = "morning.json";
const MORNING_DEFAULT = { enabled: true, mode: "auto", time: null, lastGreeted: null, lastStartDay: null, starts: [] };
const ACTIVE_IDLE_S = 120;
const DAY_STARTS_AT = 4 * 60; // activity before 4:00 belongs to the previous night
const MORNING_ENDS_AT = 12 * 60;

const dayKey = (date) => `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
const toMinutes = (hhmm) => {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm ?? ""));
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
};
const toClock = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;

function learnedStart(starts) {
  const minutes = starts.map(toMinutes).filter((m) => m !== null).sort((a, b) => a - b);
  return minutes.length >= 3 ? minutes[Math.floor(minutes.length / 2)] : null;
}

async function readMorning() {
  const saved = await readJson(MORNING_FILE, {});
  return { ...MORNING_DEFAULT, ...(saved && typeof saved === "object" ? saved : {}) };
}

async function checkMorning() {
  const state = powerMonitor.getSystemIdleState(ACTIVE_IDLE_S); // active | idle | locked
  if (state !== "active") return;
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const today = dayKey(now);
  const greet = await serial(async () => {
    const morning = await readMorning();
    let changed = false;
    if (minutes >= DAY_STARTS_AT && morning.lastStartDay !== today) {
      morning.starts = [...morning.starts, toClock(minutes)].slice(-14); // when the day started
      morning.lastStartDay = today;
      changed = true;
    }
    const learned = learnedStart(morning.starts.slice(0, -1)); // without today's
    const target =
      morning.mode === "fixed" ? toMinutes(morning.time) : learned !== null ? Math.max(DAY_STARTS_AT, learned - 30) : DAY_STARTS_AT;
    const due = morning.enabled && morning.lastGreeted !== today && target !== null && minutes >= target && minutes < MORNING_ENDS_AT;
    if (due) {
      morning.lastGreeted = today;
      changed = true;
    }
    if (changed) await writeJson(MORNING_FILE, morning);
    return due;
  });
  if (greet) config.getWindow()?.webContents.send("morning");
}

async function morningSettings() {
  const morning = await readMorning();
  const learned = learnedStart(morning.starts);
  return { enabled: morning.enabled, mode: morning.mode, time: morning.time, learned: learned === null ? null : toClock(learned) };
}

async function setMorningGreeting({ enabled = true, mode = "fixed", time = null }) {
  if (!["fixed", "auto"].includes(mode)) return { status: "error", error: "mode must be fixed or auto" };
  if (mode === "fixed" && toMinutes(time) === null) return { status: "error", error: "Give time as HH:MM" };
  await serial(async () => {
    const morning = await readMorning();
    await writeJson(MORNING_FILE, { ...morning, enabled: Boolean(enabled), mode, time: mode === "fixed" ? time : morning.time });
  });
  const saved = await morningSettings();
  return { status: "ok", ...saved };
}

let loopStarted = false;

/** Started by main once the page has loaded, so due reminders are also spoken. */
function startReminders() {
  if (loopStarted) return;
  loopStarted = true;
  const tick = () => {
    void fireDueReminders();
    void checkMorning().catch(() => undefined);
  };
  tick();
  setInterval(tick, CHECK_EVERY_MS);
}

function formatTime(ms) {
  return new Date(ms).toLocaleString("es", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
}

const REPEAT_LABELS = { daily: "todos los días", weekdays: "de lunes a viernes", weekly: "cada semana" };

async function setReminder({ text, in_minutes: inMinutes, at, repeat = "none", heads_up_minutes: headsUp = 0 }) {
  const message = String(text ?? "").trim().slice(0, 300);
  if (!message) return { status: "error", error: "Empty reminder" };
  let when = null;
  if (typeof inMinutes === "number" && inMinutes > 0) when = Date.now() + inMinutes * 60_000;
  else if (typeof at === "string") when = Date.parse(at);
  if (!when || Number.isNaN(when)) return { status: "error", error: "Give in_minutes or a valid ISO time in `at`" };
  // "Todos los días a las 7" said in the evening starts tomorrow.
  if (when < Date.now() && REPEATS.has(repeat) && repeat !== "none") when = nextOccurrence(when, repeat, Date.now());
  if (when < Date.now() - 60_000) return { status: "error", error: "That time has already passed" };
  if (when > Date.now() + MAX_REMINDER_DAYS * 86_400_000) return { status: "error", error: "Reminders up to 30 days ahead" };
  if (!REPEATS.has(repeat)) return { status: "error", error: "repeat: none, daily, weekdays or weekly" };
  const minutesBefore = Math.min(Math.max(Math.round(Number(headsUp) || 0), 0), 60);
  const reminder = { id: crypto.randomBytes(3).toString("hex"), text: message, at: when, repeat, headsUp: minutesBefore };
  await serial(async () => {
    const reminders = await readJson("reminders.json", []);
    await writeJson("reminders.json", [...reminders, reminder].sort((a, b) => fireTime(a) - fireTime(b)));
  });
  return { status: "ok", id: reminder.id, text: message, when: formatTime(when), repeat: REPEAT_LABELS[repeat] ?? "una vez" };
}

async function listReminders() {
  const reminders = await readJson("reminders.json", []);
  return {
    reminders: reminders.map((r) => ({ id: r.id, text: r.text, when: formatTime(r.at), repeat: REPEAT_LABELS[r.repeat] ?? "una vez" })),
  };
}

async function cancelReminder({ id }) {
  return serial(async () => {
    const reminders = await readJson("reminders.json", []);
    const remaining = reminders.filter((r) => r.id !== id);
    if (remaining.length === reminders.length) return { status: "not_found" };
    await writeJson("reminders.json", remaining);
    return { status: "cancelled", id };
  });
}

// ---- opening things -------------------------------------------------------------------

let appIndex = null;

/** Installed apps = Start menu shortcuts (the allow-list of what open_app can launch). */
function indexApps() {
  if (appIndex) return appIndex;
  const roots = [
    path.join(process.env.ProgramData ?? "C:\\ProgramData", "Microsoft", "Windows", "Start Menu", "Programs"),
    path.join(process.env.APPDATA ?? "", "Microsoft", "Windows", "Start Menu", "Programs"),
  ];
  const apps = [];
  const walk = (dir, depth) => {
    let entries = [];
    try {
      entries = fsSync.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory() && depth < 3) walk(full, depth + 1);
      else if (entry.isFile() && entry.name.toLowerCase().endsWith(".lnk")) {
        const name = entry.name.slice(0, -4);
        if (!/uninstall|desinstal|readme|help|ayuda/i.test(name)) apps.push({ name, path: full });
      }
    }
  };
  roots.forEach((root) => walk(root, 0));
  appIndex = apps;
  return apps;
}

// System tools that could change the computer: never opened by voice/chat.
const BLOCKED_APPS =
  /\b(cmd|simbolo del sistema|command prompt|powershell|terminal|regedit|registro|editor del registro|administrative|herramientas administrativas|windows tools|herramientas de windows|task scheduler|programador de tareas|servicios|services|computer management|administracion de equipos|ejecutar|run|recovery|recuperacion|disk|disco|bios|firmware)\b/;

function findApp(name) {
  const wanted = normalize(name);
  if (wanted.length < 2) return null; // "!" or "a" would match almost anything
  const scored = indexApps()
    .filter((a) => !BLOCKED_APPS.test(normalize(a.name)))
    .map((a) => {
      const n = normalize(a.name);
      let score = 0;
      if (n === wanted) score = 100;
      else if (n.startsWith(`${wanted} `) || n.startsWith(wanted)) score = 70;
      else if (n.includes(wanted)) score = 50;
      return { ...a, score: score - n.length / 100 };
    })
    .filter((a) => a.score >= 49)
    .sort((a, b) => b.score - a.score);
  return scored[0] ?? null;
}

async function openApp({ name }) {
  const found = findApp(String(name ?? ""));
  if (!found) {
    const examples = indexApps().slice(0, 25).map((a) => a.name).join(", ");
    return { status: "not_found", message: `No encontré «${name}» en el menú Inicio.`, some_installed_apps: examples };
  }
  const error = await shell.openPath(found.path);
  return error ? { status: "error", error } : { status: "ok", opened: found.name };
}

async function openUrl({ url }) {
  let parsed;
  try {
    parsed = new URL(String(url));
  } catch {
    return { status: "error", error: "Invalid URL" };
  }
  if (!["http:", "https:"].includes(parsed.protocol)) return { status: "error", error: "Only http(s) websites" };
  await shell.openExternal(parsed.toString());
  return { status: "ok", opened: parsed.toString() };
}

let projectsRoot = null;

/** The projects folder on this computer, as reported by the API (PROJECTS_HOST). */
async function getProjectsRoot() {
  if (projectsRoot !== null) return projectsRoot;
  try {
    const info = await (await fetch(`${config.apiUrl}/projects`)).json();
    projectsRoot = info.host_root ? path.resolve(info.host_root) : "";
  } catch {
    return "";
  }
  return projectsRoot;
}

/** Resolve a path relative to the projects folder, refusing anything outside it. */
async function insideProjects(relative) {
  const root = await getProjectsRoot();
  if (!root) return null;
  const clean = String(relative ?? "").replace(/\\/g, "/").replace(/^\/+/, "");
  if (!clean || clean.split("/").some((part) => part === ".." || part.startsWith("."))) return null;
  const full = path.resolve(root, clean);
  const inside = (candidate, base) => {
    const rel = path.relative(base, candidate);
    return Boolean(rel) && !rel.startsWith("..") && !path.isAbsolute(rel);
  };
  if (!inside(full, root)) return null;
  // Follow junctions/symlinks: the real target must also be inside the real root.
  if (fsSync.existsSync(full)) {
    try {
      if (!inside(fsSync.realpathSync(full), fsSync.realpathSync(root))) return null;
    } catch {
      return null;
    }
  }
  return full;
}

const KNOWN_FOLDERS = {
  descargas: "downloads", downloads: "downloads", escritorio: "desktop", desktop: "desktop",
  documentos: "documents", documents: "documents", musica: "music", music: "music",
  imagenes: "pictures", fotos: "pictures", pictures: "pictures", videos: "videos",
}; // fmt: skip

async function openFolder({ path: target }) {
  const key = normalize(target).replace(/^mis /, "");
  let folder = KNOWN_FOLDERS[key] ? app.getPath(KNOWN_FOLDERS[key]) : await insideProjects(target);
  if (!folder) return { status: "error", error: "Only Descargas, Escritorio, Documentos, Música, Imágenes, Videos or a folder inside the projects folder" };
  if (!fsSync.existsSync(folder) || !fsSync.statSync(folder).isDirectory()) return { status: "not_found", path: target };
  const error = await shell.openPath(folder);
  return error ? { status: "error", error } : { status: "ok", opened: folder };
}

async function openFile({ path: target }) {
  const file = await insideProjects(target);
  if (!file) return { status: "error", error: "Only files inside the projects folder (use find_files)" };
  const extension = path.extname(file).slice(1).toLowerCase();
  if (!OPENABLE_FILES.has(extension)) return { status: "error", error: `Files of type .${extension} are not opened for safety` };
  if (!fsSync.existsSync(file) || !fsSync.statSync(file).isFile()) return { status: "not_found", path: target };
  const error = await shell.openPath(file);
  return error ? { status: "error", error } : { status: "ok", opened: path.basename(file) };
}

function findVsCode() {
  const candidates = [
    path.join(process.env.LOCALAPPDATA ?? "", "Programs", "Microsoft VS Code", "Code.exe"),
    path.join(process.env.ProgramFiles ?? "C:\\Program Files", "Microsoft VS Code", "Code.exe"),
  ];
  return candidates.find((c) => fsSync.existsSync(c)) ?? null;
}

async function openInEditor({ project }) {
  const folder = await insideProjects(project);
  if (!folder || !fsSync.existsSync(folder) || !fsSync.statSync(folder).isDirectory()) {
    return { status: "not_found", error: `No encontré la carpeta «${project}» en tus proyectos` };
  }
  const code = findVsCode();
  if (code) {
    const child = spawn(code, [folder], { detached: true, stdio: "ignore" });
    child.on("error", () => undefined); // a failed start must not crash the app
    child.unref();
  } else {
    await shell.openExternal(`vscode://file/${folder.replace(/\\/g, "/")}`);
  }
  return { status: "ok", opened: path.basename(folder), editor: "Visual Studio Code" };
}

// ---- routines ---------------------------------------------------------------------------

const STEP_TOOLS = new Set(["open_app", "open_url", "open_folder", "open_in_editor", "spotify_play", "media_control"]);

async function listRoutines() {
  const routines = await readJson("routines.json", {});
  return { routines: Object.entries(routines).map(([name, r]) => ({ name, description: r.description, steps: r.steps })) };
}

async function saveRoutine({ name, description, steps }) {
  const key = normalize(name);
  if (!key || !Array.isArray(steps) || steps.length === 0 || steps.length > 10) return { status: "error", error: "Invalid routine" };
  if (steps.some((s) => !STEP_TOOLS.has(s?.tool))) return { status: "error", error: "A step uses an action that routines cannot run" };
  return serial(async () => {
    const routines = await readJson("routines.json", {});
    const replaced = key in routines;
    routines[key] = { description: String(description ?? "").slice(0, 200), steps };
    await writeJson("routines.json", routines);
    return { status: replaced ? "replaced" : "saved", name: key, steps: steps.length };
  });
}

async function runRoutine({ name }) {
  const routines = await readJson("routines.json", {});
  const routine = routines[normalize(name)];
  if (!routine) return { status: "not_found", available: Object.keys(routines) };
  const results = [];
  for (const step of routine.steps) {
    if (!STEP_TOOLS.has(step.tool)) continue;
    results.push({ step: step.tool, result: await runAction(step.tool, step.args ?? {}) });
    await new Promise((r) => setTimeout(r, 600)); // let each app start before the next one
  }
  return { status: "ok", routine: normalize(name), results };
}

// ---- clipboard and screen ---------------------------------------------------------------

async function readClipboard() {
  // Recent Electron versions may return a Promise here; await works for both.
  const text = String((await clipboard.readText()) ?? "");
  if (!text.trim()) return { status: "empty", message: "No hay texto copiado." };
  return { status: "ok", text: text.slice(0, 6000), truncated: text.length > 6000 };
}

async function writeClipboard({ text }) {
  await clipboard.writeText(String(text ?? "").slice(0, 20_000));
  return { status: "ok", copied_chars: String(text ?? "").length };
}

function withTimeout(promise, ms) {
  return Promise.race([promise, new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), ms))]);
}

async function lookAtScreen({ question }) {
  const window = config.getWindow();
  const wasVisible = Boolean(window?.isVisible() && !window.isMinimized());
  // Hide Isabel for a moment so the screenshot shows what is behind her.
  if (wasVisible) window.hide();
  await new Promise((r) => setTimeout(r, 350));
  let jpeg;
  try {
    // Never leave Isabel hidden: give up on the capture after a few seconds.
    const sources = await withTimeout(
      desktopCapturer.getSources({ types: ["screen"], thumbnailSize: { width: 1600, height: 1000 } }),
      8000,
    );
    // The screen with the mouse on it (where the user is looking), else the first one.
    const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
    const source = sources.find((s) => s.display_id === String(display.id)) ?? sources[0];
    jpeg = source?.thumbnail.toJPEG(78);
  } catch {
    jpeg = null;
  } finally {
    if (wasVisible) window.showInactive();
  }
  if (!jpeg || jpeg.length === 0) return { status: "error", error: "Could not capture the screen" };
  const response = await fetch(`${config.apiUrl}/vision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image: jpeg.toString("base64"), question: String(question ?? "").slice(0, 300) }),
    signal: AbortSignal.timeout(60_000),
  });
  if (!response.ok) return { status: "error", error: `Vision service answered ${response.status}` };
  const { answer } = await response.json();
  return { status: "ok", answer: String(answer ?? "").slice(0, 3000) };
}

// ---- dispatcher -------------------------------------------------------------------------

const HANDLERS = {
  set_reminder: setReminder,
  set_morning_greeting: setMorningGreeting,
  list_reminders: listReminders,
  cancel_reminder: cancelReminder,
  open_app: openApp,
  open_url: openUrl,
  open_folder: openFolder,
  open_file: openFile,
  open_in_editor: openInEditor,
  list_routines: listRoutines,
  save_routine: saveRoutine,
  run_routine: runRoutine,
  read_clipboard: readClipboard,
  write_clipboard: writeClipboard,
  look_at_screen: lookAtScreen,
};

const MUSIC_TOOLS = new Set(["media_control", "now_playing", "spotify_play"]);

/** Run one agent tool on this computer; always resolves to a small JSON result. */
async function runAction(tool, args) {
  try {
    if (MUSIC_TOOLS.has(tool)) return await config.runMusic(tool, args);
    const handler = HANDLERS[tool];
    if (!handler) return { status: "error", error: `Unknown computer action ${tool}` };
    return await handler(args ?? {});
  } catch (error) {
    return { status: "error", error: `The action failed: ${error.message}` };
  }
}

// Actions that need the user's approval in the chat first (checked again by main.cjs).
const NEEDS_APPROVAL = new Set(["save_routine", "read_clipboard", "write_clipboard", "look_at_screen"]);

/** open_url needs approval when the URL could carry data (same rule as the API). */
function needsApproval(tool, args) {
  if (NEEDS_APPROVAL.has(tool)) return true;
  if (tool !== "open_url") return false;
  try {
    const url = new URL(String(args?.url ?? ""));
    return Boolean(url.pathname.replace(/\//g, "") || url.search || url.hash);
  } catch {
    return true;
  }
}

module.exports = { init, runAction, showWindow, startReminders, needsApproval, morningSettings, setMorningGreeting };
