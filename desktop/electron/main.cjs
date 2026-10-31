// Electron main process: creates the window and is the only part that talks to the
// local assistant API (http://127.0.0.1:8000). The UI (renderer) has no Node access;
// it calls the small, fixed set of functions exposed in preload.cjs.

const {
  app,
  BrowserWindow,
  Menu,
  Tray,
  dialog,
  ipcMain,
  nativeImage,
  net,
  protocol,
  screen,
  session,
  shell,
} = require("electron");
const { pathToFileURL } = require("node:url");
const computer = require("./computer.cjs");
const actions = require("./desktop-actions.cjs");

let mainWindow = null;
let tray = null;
let quitting = false; // true when the user really quits (tray menu), not just closes
const fsSync = require("node:fs");
const fs = require("node:fs/promises");
const path = require("node:path");

const API_URL = (process.env.ASSISTANT_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const DEV_URL = process.env.VITE_DEV_SERVER_URL;
const SUPPORTED_DOCS = ["md", "txt", "pdf"];
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

// The local wake-word model (desktop/models/*.tar.gz) is served over a private scheme:
// the speech worker runs from a blob: URL and cannot read file:// URLs.
const MODELS_DIR = path.join(__dirname, "..", "models");
protocol.registerSchemesAsPrivileged([
  { scheme: "isabel-model", privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
]);

function serveModel(request) {
  const name = decodeURIComponent(new URL(request.url).pathname).replace(/^\/+/, "");
  // Only plain .tar.gz file names inside MODELS_DIR: no folders, no traversal.
  if (!/^[\w.-]+\.tar\.gz$/.test(name)) return new Response("not found", { status: 404 });
  return net.fetch(pathToFileURL(path.join(MODELS_DIR, name)).toString());
}

function modelInfo(event) {
  if (!trustedSender(event)) return null;
  const file = fsSync.existsSync(MODELS_DIR) ? fsSync.readdirSync(MODELS_DIR).find((f) => f.endsWith(".tar.gz")) : undefined;
  return file ? { url: `isabel-model://local/${file}` } : null;
}

// Only these API routes can be reached from the UI.
const ALLOWED_ROUTES = [
  /^GET \/health$/,
  /^POST \/chat$/,
  /^POST \/chat\/[A-Za-z0-9_-]{1,64}\/confirm$/,
  /^POST \/chat\/[A-Za-z0-9_-]{1,64}\/client-result$/,
  /^GET \/documents$/,
  /^DELETE \/documents\?source_path=[^&]+$/,
  /^GET \/memory\/facts$/,
  /^DELETE \/memory\/facts\/[A-Za-z0-9-]{1,64}$/,
  /^GET \/skills$/,
  /^DELETE \/skills\/[a-z0-9_]{1,40}$/,
  /^GET \/vault$/,
  /^GET \/habits$/,
  /^DELETE \/habits$/,
  /^GET \/projects$/,
  /^POST \/vault\/sync$/,
];

// Opens a vault note in the Obsidian app (obsidian:// link). Only that scheme, only
// vault-relative .md paths.
async function openInObsidian(event, { vault, file }) {
  if (!trustedSender(event)) return false;
  const valid =
    typeof vault === "string" && vault.length > 0 && vault.length < 200 &&
    typeof file === "string" && /\.md$/i.test(file) && !/[\\:]/.test(file) &&
    !file.split("/").some((p) => p === ".." || p.startsWith("."));
  if (!valid) return false;
  const url = `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(file.replace(/\.md$/i, ""))}`;
  await shell.openExternal(url);
  return true;
}

async function readJson(response) {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch {
    return { detail: text };
  }
}

// IPC is only answered for our own page (dev server or the bundled index.html).
function trustedSender(event) {
  const url = event.senderFrame?.url ?? "";
  return DEV_URL ? url.startsWith(DEV_URL) : url.startsWith("file://") && url.includes("/dist/index.html");
}

const FORBIDDEN = { ok: false, status: 403, data: { detail: "forbidden" } };

async function apiRequest(event, { method, route, body }) {
  if (!trustedSender(event) || !ALLOWED_ROUTES.some((rule) => rule.test(`${method} ${route}`))) {
    return FORBIDDEN;
  }
  try {
    const response = await fetch(`${API_URL}${route}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    return { ok: response.ok, status: response.status, data: await readJson(response) };
  } catch {
    return { ok: false, status: 0, data: { detail: "api_unreachable" } };
  }
}

async function postForm(route, form) {
  try {
    const response = await fetch(`${API_URL}${route}`, { method: "POST", body: form });
    return { ok: response.ok, status: response.status, data: await readJson(response) };
  } catch {
    return { ok: false, status: 0, data: { detail: "api_unreachable" } };
  }
}

async function pickAndIngest(event) {
  if (!trustedSender(event)) return FORBIDDEN;
  const window = BrowserWindow.fromWebContents(event.sender);
  const picked = await dialog.showOpenDialog(window, {
    title: "Añadir notas al asistente",
    properties: ["openFile", "multiSelections"],
    filters: [{ name: "Notas", extensions: SUPPORTED_DOCS }],
  });
  if (picked.canceled || picked.filePaths.length === 0) {
    return { ok: true, status: 200, data: { results: [] } };
  }
  const form = new FormData();
  const tooLarge = [];
  let added = 0;
  for (const filePath of picked.filePaths) {
    // Check the size before reading, so huge files are never loaded into memory.
    if ((await fs.stat(filePath)).size > MAX_UPLOAD_BYTES) {
      tooLarge.push(path.basename(filePath));
      continue;
    }
    // The file name (not the full path) identifies the document: no host paths leave the UI.
    form.append("files", new Blob([await fs.readFile(filePath)]), path.basename(filePath));
    added += 1;
  }
  const skipped = tooLarge.map((name) => ({
    source_path: name,
    status: "skipped",
    chunks: 0,
    message: "Más de 20 MB",
  }));
  if (added === 0) return { ok: true, status: 200, data: { results: skipped } };
  const response = await postForm("/ingest", form);
  if (response.ok) response.data.results = [...(response.data.results ?? []), ...skipped];
  return response;
}

// Natural spoken reply: the API returns a WAV, handed to the UI as bytes.
async function speakNatural(event, { text, voice }) {
  if (!trustedSender(event) || typeof text !== "string" || !text.trim()) return FORBIDDEN;
  try {
    const response = await fetch(`${API_URL}/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text.slice(0, 1500), voice: typeof voice === "string" ? voice : null }),
    });
    if (!response.ok) return { ok: false, status: response.status, data: await readJson(response) };
    return { ok: true, status: 200, data: { audio: new Uint8Array(await response.arrayBuffer()) } };
  } catch {
    return { ok: false, status: 0, data: { detail: "api_unreachable" } };
  }
}

async function transcribe(event, wavBytes) {
  if (!trustedSender(event)) return FORBIDDEN;
  const form = new FormData();
  form.append("audio", new Blob([Buffer.from(wavBytes)], { type: "audio/wav" }), "voz.wav");
  return postForm("/transcribe", form);
}

// Orb and app preferences live in the user's profile folder, not in the repo.
const settingsFile = () => path.join(app.getPath("userData"), "settings.json");

async function loadSettings() {
  try {
    return JSON.parse(await fs.readFile(settingsFile(), "utf-8"));
  } catch {
    return null;
  }
}

async function saveSettings(event, settings) {
  if (!trustedSender(event)) return false;
  await fs.writeFile(settingsFile(), JSON.stringify(settings, null, 2), "utf-8");
  return true;
}

// The window material is chosen at startup (it cannot change on a live window):
// - "glass": fully transparent, frameless window; the desktop shows through sharply and the
//   page draws its own window buttons.
// - "acrylic": Windows 11 blurs what is behind the window; native window buttons.
function windowMaterial() {
  try {
    const saved = JSON.parse(fsSync.readFileSync(settingsFile(), "utf-8"));
    return saved.backgroundMaterial === "acrylic" ? "acrylic" : "glass";
  } catch {
    return "glass";
  }
}

let material = "glass";

function materialOptions() {
  if (material === "acrylic") {
    return {
      backgroundColor: "#00000000",
      backgroundMaterial: "acrylic",
      titleBarStyle: "hidden",
      titleBarOverlay: { color: "#00000000", symbolColor: "#8a8f9c", height: 36 },
    };
  }
  return { transparent: true, frame: false, backgroundColor: "#00000000", hasShadow: false };
}

// Window buttons drawn by the page (glass mode). Transparent windows cannot use the
// native maximize on Windows, so "maximize" fills the screen's work area instead.
const restoreBounds = new WeakMap();

function windowControl(event, action) {
  if (!trustedSender(event)) return false;
  const window = BrowserWindow.fromWebContents(event.sender);
  if (!window) return false;
  if (action === "minimize") window.minimize();
  else if (action === "close") window.close();
  else if (action === "maximize") {
    const previous = restoreBounds.get(window);
    if (previous) {
      window.setBounds(previous);
      restoreBounds.delete(window);
    } else {
      restoreBounds.set(window, window.getBounds());
      window.setBounds(screen.getDisplayMatching(window.getBounds()).workArea);
    }
  }
  return true;
}

/** True if the API has exactly this computer action waiting (it exists only after approval). */
async function isApprovedAction(threadId, toolCallId, tool, args) {
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(String(threadId)) || !toolCallId) return false;
  try {
    const response = await fetch(`${API_URL}/chat/${threadId}/pending-action`);
    if (!response.ok) return false;
    const pending = await response.json();
    return (
      pending.kind === "client_action" &&
      pending.tool_call_id === toolCallId &&
      pending.tool === tool &&
      JSON.stringify(pending.args) === JSON.stringify(args ?? {})
    );
  } catch {
    return false;
  }
}

function closeToTray() {
  try {
    const saved = JSON.parse(fsSync.readFileSync(settingsFile(), "utf-8"));
    return saved.closeToTray !== false;
  } catch {
    return true;
  }
}

function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, "..", "assets", "tray.png"));
  tray = new Tray(icon);
  tray.setToolTip("Isabel");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Abrir Isabel", click: () => (mainWindow ? actions.showWindow() : createWindow()) },
      { type: "separator" },
      {
        label: "Salir",
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("click", () => (mainWindow ? actions.showWindow() : createWindow()));
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 720,
    minHeight: 520,
    title: "Isabel",
    ...materialOptions(),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.setMenuBarVisibility(false);
  mainWindow = window;
  // Closing the window keeps Isabel in the tray (reminders and "Isabel" keep working),
  // unless the user turned that off in the settings or quits from the tray menu.
  window.on("close", (event) => {
    if (!quitting && closeToTray()) {
      event.preventDefault();
      window.hide();
    }
  });
  window.on("closed", () => {
    if (mainWindow === window) mainWindow = null;
  });
  // The window only ever shows our page: no popups, no navigation (e.g. a dropped file).
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  // Reminders start once the page can speak them (also those already due at startup).
  window.webContents.once("did-finish-load", () => actions.startReminders());
  // ASSISTANT_DEBUG=1 copies the page's console to the terminal (useful when testing).
  if (process.env.ASSISTANT_DEBUG) {
    window.webContents.on("console-message", (details) => {
      process.stderr.write(`[renderer] ${details.message}\n`);
    });
  }
  // The floating status bar appears while this window is minimized or hidden.
  for (const change of ["minimize", "restore", "hide", "show"]) window.on(change, updateStatusBar);
  window.on("closed", () => statusWindow?.destroy());
  if (DEV_URL) window.loadURL(DEV_URL);
  else window.loadFile(path.join(__dirname, "..", "dist", "index.html"));
}

// --- Floating status bar ----------------------------------------------------------------
// A small always-on-top pill at the top of the screen: listening / thinking / speaking,
// plus mute and "write" buttons. The main window owns the state and reports it here.
// It rests as a thin strip (like a phone's home bar) and opens when the mouse comes near.
const STATUS_SIZES = {
  collapsed: { width: 220, height: 16, top: 0 },
  expanded: { width: 440, height: 52, top: 6 },
  answer: { width: 440, height: 140, top: 6 },
};
const STATUS_PAGE = path.join(__dirname, "statusbar", "statusbar.html");
let statusWindow = null;
let lastStatus = { phase: "idle", micOn: true, wakeReady: false, statusBar: true, answer: "", answerId: "" };

function statusSender(event) {
  return (event.senderFrame?.url ?? "") === pathToFileURL(STATUS_PAGE).toString();
}

function statusBounds(mode) {
  const size = STATUS_SIZES[mode] ?? STATUS_SIZES.collapsed;
  const area = screen.getPrimaryDisplay().workArea;
  return { x: Math.round(area.x + (area.width - size.width) / 2), y: area.y + size.top, width: size.width, height: size.height };
}

function createStatusWindow() {
  const window = new BrowserWindow({
    ...statusBounds("collapsed"),
    frame: false,
    transparent: true,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    hasShadow: false,
    show: false,
    title: "Isabel · estado",
    webPreferences: {
      preload: path.join(__dirname, "statusbar-preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.setAlwaysOnTop(true, "floating");
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  window.webContents.on("did-finish-load", () => window.webContents.send("status", lastStatus));
  window.on("closed", () => {
    if (statusWindow === window) statusWindow = null;
  });
  window.loadFile(STATUS_PAGE);
  statusWindow = window;
}

function updateStatusBar() {
  const away = mainWindow && (!mainWindow.isVisible() || mainWindow.isMinimized());
  if (away && lastStatus.statusBar && !quitting) {
    if (!statusWindow) createStatusWindow();
    if (!statusWindow.isVisible()) {
      statusWindow.setBounds(statusBounds("collapsed"));
      statusWindow.setIgnoreMouseEvents(true, { forward: true });
      statusWindow.webContents.send("collapse");
      statusWindow.showInactive(); // never steals the focus
    }
  } else if (statusWindow?.isVisible()) {
    statusWindow.hide();
  }
}

function onStatusUpdate(event, status) {
  if (!trustedSender(event) || typeof status !== "object" || status === null) return;
  lastStatus = {
    phase: String(status.phase ?? "idle").slice(0, 20),
    micOn: status.micOn === true,
    wakeReady: status.wakeReady === true,
    statusBar: status.statusBar !== false,
    answer: String(status.answer ?? "").slice(0, 400),
    answerId: String(status.answerId ?? "").slice(0, 40),
  };
  statusWindow?.webContents.send("status", lastStatus);
  updateStatusBar();
}

// Only three commands, all things the user could do in the main window; the bar can never
// approve an action.
function onStatusBarCommand(event, command) {
  if (!statusSender(event) || typeof command !== "object" || command === null) return;
  if (command.type === "open") actions.showWindow();
  else if (command.type === "toggleMic") mainWindow?.webContents.send("statusbar:command", { type: "toggleMic" });
  else if (command.type === "send" && typeof command.text === "string" && command.text.trim()) {
    mainWindow?.webContents.send("statusbar:command", { type: "send", text: command.text.trim().slice(0, 8000) });
  }
}

function onStatusBarResize(event, mode) {
  if (!statusSender(event) || !statusWindow || !Object.hasOwn(STATUS_SIZES, mode)) return;
  statusWindow.setBounds(statusBounds(mode));
  // Collapsed, clicks go through to whatever is underneath (Windows keeps the window
  // taller than the strip); mouse moves are still forwarded so the strip can open.
  statusWindow.setIgnoreMouseEvents(mode === "collapsed", { forward: true });
}

app.setAppUserModelId("Isabel"); // so Windows shows the app's notifications (reminders)

app.whenReady().then(async () => {
  if (process.argv.includes("--spotify-diagnose")) {
    // Troubleshooting only: print what Spotify reports (devices, player) and quit.
    process.stdout.write(`${JSON.stringify(await computer.diagnose(), null, 2)}\n`);
    app.quit();
    return;
  }
  const runOne = process.argv.indexOf("--run-action");
  if (runOne !== -1) {
    // Troubleshooting only: run one computer action exactly like the agent would.
    actions.init({ apiUrl: API_URL, getWindow: () => null, runMusic: (t, a) => computer.runAction(t, a) });
    const tool = process.argv[runOne + 1] ?? "";
    const args = JSON.parse(process.argv[runOne + 2] ?? "{}");
    process.stdout.write(`${JSON.stringify(await actions.runAction(tool, args), null, 2)}\n`);
    if (process.argv.includes("--wait")) actions.startReminders(); // only when testing reminders
    if (!process.argv.includes("--wait")) {
      app.quit();
      return;
    }
    setTimeout(() => app.quit(), 25_000); // keep running so a short reminder can fire
    return;
  }
  const testPlay = process.argv.indexOf("--spotify-test-play");
  if (testPlay !== -1) {
    // Troubleshooting only: play one song exactly like the agent would, print the result.
    const query = process.argv[testPlay + 1] ?? "";
    const artist = process.argv[testPlay + 2] ?? "";
    const played = await computer.runAction("spotify_play", { query, artist, kind: "track" });
    process.stdout.write(`${JSON.stringify(played, null, 2)}\n`);
    app.quit();
    return;
  }
  // The microphone (audio only, never the camera) is the only permission the UI may get.
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback, details) => {
    const types = details.mediaTypes ?? [];
    callback(permission === "media" && types.length > 0 && types.every((t) => t === "audio"));
  });
  ipcMain.handle("api:request", apiRequest);
  ipcMain.handle("docs:pick-and-ingest", pickAndIngest);
  ipcMain.handle("voice:transcribe", transcribe);
  ipcMain.handle("voice:speak", speakNatural);
  ipcMain.handle("settings:load", loadSettings);
  ipcMain.handle("settings:save", saveSettings);
  protocol.handle("isabel-model", serveModel);
  ipcMain.handle("wake:model", modelInfo);
  ipcMain.handle("obsidian:open", openInObsidian);
  // Actions on this computer (music, Spotify) requested by the agent.
  ipcMain.handle("computer:run", async (event, { tool, args, threadId, toolCallId }) => {
    if (!trustedSender(event)) return FORBIDDEN.data;
    const name = String(tool);
    // Risky actions run only if the API really has this approved action waiting
    // (defense in depth: even a compromised page cannot skip the user's approval).
    if (actions.needsApproval(name, args) && !(await isApprovedAction(threadId, toolCallId, name, args))) {
      return { status: "error", error: "This action was not approved by the user." };
    }
    return actions.runAction(name, args ?? {});
  });
  ipcMain.handle("spotify:status", (event) => (trustedSender(event) ? computer.status() : null));
  ipcMain.handle("spotify:connect", (event, clientId) =>
    trustedSender(event) ? computer.connect(String(clientId ?? "").trim()) : { ok: false },
  );
  ipcMain.handle("spotify:disconnect", (event) => (trustedSender(event) ? computer.disconnect() : { ok: false }));
  ipcMain.handle("window:info", (event) => (trustedSender(event) ? { customControls: material === "glass", material } : null));
  ipcMain.handle("window:control", windowControl);
  ipcMain.handle("morning:get", (event) => (trustedSender(event) ? actions.morningSettings() : null));
  ipcMain.handle("morning:set", (event, value) =>
    trustedSender(event) && value && typeof value === "object" ? actions.setMorningGreeting(value) : null,
  );
  ipcMain.on("status:update", onStatusUpdate);
  ipcMain.on("statusbar:command", onStatusBarCommand);
  ipcMain.on("statusbar:resize", onStatusBarResize);
  ipcMain.handle("app:relaunch", (event) => {
    if (!trustedSender(event)) return false;
    app.relaunch();
    app.exit(0);
    return true;
  });
  material = windowMaterial();
  actions.init({
    apiUrl: API_URL,
    getWindow: () => mainWindow,
    runMusic: (tool, args) => computer.runAction(tool, args),
  });
  createWindow();
  createTray();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

// Only one Isabel at a time: a second launch just shows the running one. (The
// troubleshooting flags run alongside the app.)
const troubleshooting = process.argv.some((arg) => arg.startsWith("--spotify-") || arg === "--run-action");
if (!troubleshooting && !app.requestSingleInstanceLock()) {
  app.exit(0); // immediately: no window, tray or reminder loop in the second process
} else {
  app.on("second-instance", () => actions.showWindow());
}

app.on("before-quit", () => {
  quitting = true;
});

app.on("window-all-closed", () => {
  // With "keep in tray" off, closing the window quits the app.
  if (process.platform !== "darwin" && (quitting || !closeToTray())) app.quit();
});
