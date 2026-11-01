// Google Calendar and Gmail for Isabel, through the official REST APIs, with the user's own
// OAuth client ("Desktop app" in Google Cloud). Sign-in uses PKCE with a loopback redirect
// on 127.0.0.1; the refresh token and the client secret are stored encrypted with the OS
// (Electron safeStorage) and never reach the API, the model or the page.
//
// What Isabel can do: read calendar events, create an event (only after the user approves
// it in the chat), read recent emails (sender, subject, snippet) and warn before upcoming
// events. She cannot send, delete or change emails.

const { app, net, safeStorage, shell } = require("electron");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const http = require("node:http");
const path = require("node:path");

const SCOPES = ["https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/gmail.readonly"];
const AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const TOKEN_URL = "https://oauth2.googleapis.com/token";
const CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary";
const GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me";
const MAX_EVENTS = 25;
const MAX_EMAILS = 10;
const ALERT_MINUTES = 15; // "en 15 minutos tienes…"
const WATCH_EVERY_MS = 5 * 60_000;

const storeFile = () => path.join(app.getPath("userData"), "google.json");
const encrypt = (text) => (text && safeStorage.isEncryptionAvailable() ? safeStorage.encryptString(text).toString("base64") : null);
const decrypt = (text) => (text && safeStorage.isEncryptionAvailable() ? safeStorage.decryptString(Buffer.from(text, "base64")) : null);

async function readStore() {
  try {
    const saved = JSON.parse(await fs.readFile(storeFile(), "utf-8"));
    return { clientId: saved.clientId ?? "", clientSecret: decrypt(saved.clientSecret), refreshToken: decrypt(saved.refreshToken) };
  } catch {
    return { clientId: "", clientSecret: null, refreshToken: null };
  }
}

async function writeStore({ clientId, clientSecret, refreshToken }) {
  const data = { clientId, clientSecret: encrypt(clientSecret), refreshToken: encrypt(refreshToken) };
  await fs.writeFile(storeFile(), JSON.stringify(data), "utf-8");
}

let accessToken = null;
let accessExpires = 0;

async function tokenRequest(params) {
  const response = await net.fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(params).toString(),
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`Google token error ${response.status}`);
  return response.json();
}

async function getAccessToken() {
  if (accessToken && Date.now() < accessExpires - 60_000) return accessToken;
  const store = await readStore();
  if (!store.clientId || !store.refreshToken) return null;
  const data = await tokenRequest({
    grant_type: "refresh_token",
    refresh_token: store.refreshToken,
    client_id: store.clientId,
    client_secret: store.clientSecret ?? "",
  });
  accessToken = data.access_token;
  accessExpires = Date.now() + data.expires_in * 1000;
  return accessToken;
}

async function googleApi(method, url, body, retried = false) {
  const token = await getAccessToken();
  if (!token) return { notConnected: true };
  const response = await net.fetch(url, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(20_000),
  });
  if (response.status === 401 && !retried) {
    accessToken = null; // expired early or revoked: refresh once and retry
    return googleApi(method, url, body, true);
  }
  const data = await response.json().catch(() => null);
  return { ok: response.ok, status: response.status, data };
}

const NOT_CONNECTED = { status: "error", error: "Google is not connected. Tell the user: Ajustes → Google." };

/** Opens Google's sign-in in the browser and waits for the redirect on 127.0.0.1. */
async function connect({ clientId, clientSecret }) {
  clientId = String(clientId ?? "").trim();
  clientSecret = String(clientSecret ?? "").trim();
  if (!/^[\w-]+\.apps\.googleusercontent\.com$/.test(clientId)) {
    return { ok: false, error: "El Client ID termina en .apps.googleusercontent.com." };
  }
  if (clientSecret.length < 10) return { ok: false, error: "Falta el Client Secret." };
  const verifier = crypto.randomBytes(48).toString("base64url");
  const challenge = crypto.createHash("sha256").update(verifier).digest("base64url");
  const state = crypto.randomBytes(16).toString("hex");
  let redirectUri = "";

  const code = await new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, "http://127.0.0.1");
      if (url.pathname !== "/callback") {
        res.writeHead(404).end();
        return;
      }
      const ok = url.searchParams.get("state") === state && url.searchParams.get("code");
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(ok ? "<h2>Isabel ya está conectada a Google. Puedes cerrar esta pestaña.</h2>" : "<h2>No se pudo conectar. Vuelve a intentarlo desde Isabel.</h2>");
      server.close();
      clearTimeout(timer);
      if (ok) resolve(url.searchParams.get("code"));
      else reject(new Error(url.searchParams.get("error") || "state mismatch"));
    });
    const timer = setTimeout(() => {
      server.close();
      reject(new Error("timeout"));
    }, 180_000);
    server.on("error", reject);
    // Any free port: Google accepts loopback redirects on any port for Desktop clients.
    server.listen(0, "127.0.0.1", () => {
      redirectUri = `http://127.0.0.1:${server.address().port}/callback`;
      const query = new URLSearchParams({
        client_id: clientId,
        response_type: "code",
        redirect_uri: redirectUri,
        scope: SCOPES.join(" "),
        code_challenge_method: "S256",
        code_challenge: challenge,
        access_type: "offline",
        prompt: "consent",
        state,
      });
      void shell.openExternal(`${AUTH_URL}?${query}`);
    });
  }).catch((error) => ({ error }));

  if (typeof code !== "string") return { ok: false, error: `Conexión cancelada (${code.error?.message ?? "error"}).` };
  try {
    const tokens = await tokenRequest({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
      client_id: clientId,
      client_secret: clientSecret,
      code_verifier: verifier,
    });
    if (!tokens.refresh_token) return { ok: false, error: "Google no devolvió acceso permanente. Vuelve a intentarlo." };
    accessToken = tokens.access_token;
    accessExpires = Date.now() + tokens.expires_in * 1000;
    await writeStore({ clientId, clientSecret, refreshToken: tokens.refresh_token });
    return { ok: true };
  } catch (error) {
    return { ok: false, error: `No se pudo completar la conexión (${error.message}).` };
  }
}

async function status() {
  const store = await readStore();
  return { connected: Boolean(store.clientId && store.refreshToken), clientId: store.clientId };
}

async function disconnect() {
  const store = await readStore();
  accessToken = null;
  await writeStore({ clientId: store.clientId, clientSecret: store.clientSecret, refreshToken: null });
  return { ok: true };
}

// ---- calendar ---------------------------------------------------------------------------

function describeEvent(event) {
  const start = event.start?.dateTime ?? event.start?.date ?? "";
  const end = event.end?.dateTime ?? event.end?.date ?? "";
  return {
    title: String(event.summary ?? "(sin título)").slice(0, 200),
    start,
    end,
    all_day: !event.start?.dateTime,
    location: event.location ? String(event.location).slice(0, 200) : undefined,
  };
}

async function listEvents({ start_from: from, days = 1, query } = {}) {
  const start = from ? new Date(from) : new Date(new Date().setHours(0, 0, 0, 0));
  if (Number.isNaN(start.getTime())) return { status: "error", error: "Invalid start_from date" };
  const end = new Date(start.getTime() + Math.min(Math.max(Number(days) || 1, 1), 31) * 86_400_000);
  const params = new URLSearchParams({
    timeMin: start.toISOString(),
    timeMax: end.toISOString(),
    singleEvents: "true",
    orderBy: "startTime",
    maxResults: String(MAX_EVENTS),
  });
  if (query) params.set("q", String(query).slice(0, 100));
  const result = await googleApi("GET", `${CALENDAR}/events?${params}`);
  if (result.notConnected) return NOT_CONNECTED;
  if (!result.ok) return { status: "error", error: `Google Calendar answered ${result.status}` };
  return { status: "ok", events: (result.data?.items ?? []).map(describeEvent) };
}

async function createEvent({ title, start, end, description }) {
  const startDate = new Date(String(start ?? ""));
  if (!title || Number.isNaN(startDate.getTime())) return { status: "error", error: "Give a title and a valid start time" };
  const endDate = end ? new Date(String(end)) : new Date(startDate.getTime() + 60 * 60_000); // 1 h by default
  if (Number.isNaN(endDate.getTime()) || endDate <= startDate) return { status: "error", error: "The end must be after the start" };
  const body = {
    summary: String(title).slice(0, 200),
    description: description ? String(description).slice(0, 2000) : undefined,
    start: { dateTime: startDate.toISOString() },
    end: { dateTime: endDate.toISOString() },
  };
  const result = await googleApi("POST", `${CALENDAR}/events`, body);
  if (result.notConnected) return NOT_CONNECTED;
  if (!result.ok) return { status: "error", error: `Google Calendar answered ${result.status}` };
  return { status: "ok", created: describeEvent(result.data ?? {}) };
}

// ---- gmail (read only) -------------------------------------------------------------------

async function searchEmails({ query = "is:unread newer_than:2d", max = 8 } = {}) {
  const params = new URLSearchParams({ q: String(query).slice(0, 200), maxResults: String(Math.min(Math.max(Number(max) || 8, 1), MAX_EMAILS)) });
  const list = await googleApi("GET", `${GMAIL}/messages?${params}`);
  if (list.notConnected) return NOT_CONNECTED;
  if (!list.ok) return { status: "error", error: `Gmail answered ${list.status}` };
  const emails = [];
  for (const { id } of list.data?.messages ?? []) {
    const headers = ["From", "Subject", "Date"].map((h) => `metadataHeaders=${h}`).join("&");
    const message = await googleApi("GET", `${GMAIL}/messages/${id}?format=metadata&${headers}`);
    if (!message.ok) continue;
    const header = (name) => message.data?.payload?.headers?.find((h) => h.name === name)?.value ?? "";
    emails.push({
      from: header("From").slice(0, 120),
      subject: header("Subject").slice(0, 200),
      date: header("Date"),
      snippet: String(message.data?.snippet ?? "").slice(0, 300),
      unread: (message.data?.labelIds ?? []).includes("UNREAD"),
    });
  }
  // Email text is untrusted data written by strangers: the agent's prompt says so.
  return { status: "ok", emails };
}

// ---- alerts before events -----------------------------------------------------------------

const announced = new Set();

/** Every few minutes: warn ALERT_MINUTES before each timed event of the next half hour. */
function watchEvents(notify) {
  const check = async () => {
    if (!(await status()).connected) return;
    const now = Date.now();
    const result = await listEvents({ start_from: new Date(now).toISOString(), days: 1 }).catch(() => null);
    for (const event of result?.events ?? []) {
      if (event.all_day) continue;
      const start = new Date(event.start).getTime();
      const key = `${event.title}@${event.start}`;
      if (start - now <= ALERT_MINUTES * 60_000 && start > now && !announced.has(key)) {
        announced.add(key);
        notify({ text: `tu evento «${event.title}»`, at: start, early: true });
      }
    }
  };
  void check();
  setInterval(() => void check(), WATCH_EVERY_MS);
}

const HANDLERS = {
  calendar_events: listEvents,
  calendar_create_event: createEvent,
  gmail_search: searchEmails,
};

module.exports = { HANDLERS, connect, status, disconnect, watchEvents };
