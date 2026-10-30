// Actions on the user's computer, requested by the agent and run here, in the Electron
// main process (the API runs in Docker and cannot touch the desktop):
// - media_control: Windows media keys (works with Spotify and any player);
// - now_playing:   Spotify's current song (Web API if connected, else its window title);
// - spotify_play:  search + play through the official Spotify Web API (Premium), or open
//                  the search in Spotify when it is not connected.
// Spotify login uses OAuth "Authorization Code with PKCE": no client secret, no password in
// the app; the refresh token is stored encrypted with the OS (Electron safeStorage).

const { app, net, safeStorage, shell } = require("electron");
const { execFile } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");

const REDIRECT_PORT = 8888;
const REDIRECT_URI = `http://127.0.0.1:${REDIRECT_PORT}/callback`;
const SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing";
const ACCOUNTS = "https://accounts.spotify.com";
const API = "https://api.spotify.com/v1";

// Windows virtual-key codes for the media keys.
const MEDIA_KEYS = {
  play_pause: 0xb3,
  next: 0xb0,
  previous: 0xb1,
  volume_up: 0xaf,
  volume_down: 0xae,
  mute: 0xad,
};

function powershell(script) {
  return new Promise((resolve, reject) => {
    execFile(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
      { windowsHide: true, timeout: 10000 },
      (error, stdout) => (error ? reject(error) : resolve(String(stdout).trim())),
    );
  });
}

async function pressMediaKey(action) {
  const code = MEDIA_KEYS[action];
  if (code === undefined) return { status: "error", error: `Unknown action ${action}` };
  if (process.platform !== "win32") return { status: "error", error: "Media keys are only implemented on Windows" };
  // Volume steps are small: press a few times so the change is noticeable.
  const times = action.startsWith("volume") ? 5 : 1;
  await powershell(
    `$s='[DllImport("user32.dll")] public static extern void keybd_event(byte b, byte s, uint f, UIntPtr e);';` +
      `$k=Add-Type -MemberDefinition $s -Name K -Namespace W -PassThru;` +
      `1..${times} | % { $k::keybd_event(${code},0,0,[UIntPtr]::Zero); $k::keybd_event(${code},0,2,[UIntPtr]::Zero) }`,
  );
  return { status: "ok", action };
}

/** "Artist - Song" from Spotify's window title ("Spotify Premium" when paused). */
async function spotifyWindowTitle() {
  if (process.platform !== "win32") return null;
  const title = await powershell(
    "(Get-Process Spotify -ErrorAction SilentlyContinue | Where-Object MainWindowTitle | Select-Object -First 1).MainWindowTitle",
  ).catch(() => "");
  return title || null;
}

// ---- Spotify Web API (PKCE) ---------------------------------------------------------------

const storeFile = () => path.join(app.getPath("userData"), "spotify.json");

async function readStore() {
  try {
    const saved = JSON.parse(await fs.readFile(storeFile(), "utf-8"));
    let refreshToken = null;
    if (saved.refreshToken && safeStorage.isEncryptionAvailable()) {
      refreshToken = safeStorage.decryptString(Buffer.from(saved.refreshToken, "base64"));
    }
    return { clientId: saved.clientId ?? "", refreshToken };
  } catch {
    return { clientId: "", refreshToken: null };
  }
}

async function writeStore({ clientId, refreshToken }) {
  const encrypted =
    refreshToken && safeStorage.isEncryptionAvailable()
      ? safeStorage.encryptString(refreshToken).toString("base64")
      : null;
  await fs.writeFile(storeFile(), JSON.stringify({ clientId, refreshToken: encrypted }), "utf-8");
}

let accessToken = null;
let accessExpires = 0;

/**
 * fetch through Chromium's network stack (system proxy, DNS, IPv4/IPv6 fallback), with a
 * timeout and a few retries: a momentary network hiccup used to surface as "fetch failed"
 * and the song did not play.
 */
async function robustFetch(url, options = {}, attempts = 3) {
  let lastError;
  for (let i = 0; i < attempts; i++) {
    try {
      return await net.fetch(url, { ...options, signal: AbortSignal.timeout(15_000) });
    } catch (error) {
      lastError = error;
      await new Promise((r) => setTimeout(r, 600 * (i + 1)));
    }
  }
  throw new Error(`No pude conectar con Spotify (${lastError?.message ?? "red"}). Revisa tu conexión a internet.`);
}

async function tokenRequest(params) {
  const response = await robustFetch(`${ACCOUNTS}/api/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(params).toString(),
  });
  if (!response.ok) throw new Error(`Spotify token error ${response.status}`);
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
  });
  accessToken = data.access_token;
  accessExpires = Date.now() + data.expires_in * 1000;
  if (data.refresh_token) await writeStore({ clientId: store.clientId, refreshToken: data.refresh_token });
  return accessToken;
}

async function spotifyApi(method, route, body, retried = false) {
  const token = await getAccessToken();
  if (!token) return { notConnected: true };
  const response = await robustFetch(`${API}${route}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status === 401 && !retried) {
    // The access token expired early or was revoked: refresh it once and retry.
    accessToken = null;
    return spotifyApi(method, route, body, true);
  }
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (process.env.ASSISTANT_DEBUG) {
    const error = data?.error ? ` ${JSON.stringify(data.error)}` : "";
    process.stderr.write(`[spotify] ${method} ${route.split("?")[0]} -> ${response.status}${error}\n`);
  }
  return { ok: response.ok, status: response.status, data };
}

/** Opens the Spotify login in the browser and waits for the redirect on 127.0.0.1. */
async function connect(clientId) {
  if (!/^[0-9a-f]{32}$/i.test(clientId)) return { ok: false, error: "El Client ID debe tener 32 caracteres hexadecimales." };
  const verifier = crypto.randomBytes(48).toString("base64url");
  const challenge = crypto.createHash("sha256").update(verifier).digest("base64url");
  const state = crypto.randomBytes(16).toString("hex");

  const code = await new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, REDIRECT_URI);
      if (url.pathname !== "/callback") {
        res.writeHead(404).end();
        return;
      }
      const ok = url.searchParams.get("state") === state && url.searchParams.get("code");
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(
        ok
          ? "<h2>Isabel ya está conectada a Spotify. Puedes cerrar esta pestaña.</h2>"
          : "<h2>No se pudo conectar. Vuelve a intentarlo desde Isabel.</h2>",
      );
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
    server.listen(REDIRECT_PORT, "127.0.0.1", () => {
      const query = new URLSearchParams({
        client_id: clientId,
        response_type: "code",
        redirect_uri: REDIRECT_URI,
        code_challenge_method: "S256",
        code_challenge: challenge,
        scope: SCOPES,
        state,
      });
      void shell.openExternal(`${ACCOUNTS}/authorize?${query}`);
    });
  }).catch((error) => ({ error }));

  if (typeof code !== "string") return { ok: false, error: `Conexión cancelada (${code.error?.message ?? "error"}).` };
  const tokens = await tokenRequest({
    grant_type: "authorization_code",
    code,
    redirect_uri: REDIRECT_URI,
    client_id: clientId,
    code_verifier: verifier,
  });
  accessToken = tokens.access_token;
  accessExpires = Date.now() + tokens.expires_in * 1000;
  await writeStore({ clientId, refreshToken: tokens.refresh_token });
  return { ok: true };
}

async function status() {
  const store = await readStore();
  return { connected: Boolean(store.clientId && store.refreshToken), clientId: store.clientId };
}

async function disconnect() {
  const store = await readStore();
  accessToken = null;
  await writeStore({ clientId: store.clientId, refreshToken: null });
  return { ok: true };
}

function describeItem(item) {
  if (!item) return null;
  const artists = (item.artists ?? []).map((a) => a.name).join(", ");
  return artists ? `${item.name} — ${artists}` : item.name;
}

async function nowPlaying() {
  const api = await spotifyApi("GET", "/me/player/currently-playing");
  if (!api.notConnected && api.ok) {
    if (!api.data?.item) return { status: "ok", playing: false, message: "No suena nada en Spotify." };
    return { status: "ok", playing: Boolean(api.data.is_playing), song: describeItem(api.data.item) };
  }
  const title = await spotifyWindowTitle();
  if (!title) return { status: "ok", playing: false, message: "Spotify no está abierto." };
  if (/^spotify/i.test(title)) return { status: "ok", playing: false, message: "Spotify está en pausa." };
  return { status: "ok", playing: true, song: title };
}

/** How well a search result matches what was asked (title first, then artist). */
function matchScore(candidate, title, artist) {
  // "Parce (feat. Lenny Tavárez)" → "parce": ignore featuring/version notes.
  const name = normalize(candidate.name.replace(/\s*[([].*?[)\]]/g, "").replace(/\s+-\s+.*$/, ""));
  const wanted = normalize(title);
  let score = 0;
  if (name === wanted) score += 100;
  else if (name.startsWith(wanted) || wanted.startsWith(name)) score += 60;
  else if (name.includes(wanted)) score += 30;
  if (artist) {
    const artists = (candidate.artists ?? []).map((a) => normalize(a.name));
    if (candidate.type === "artist") artists.push(normalize(candidate.name));
    if (artists.some((a) => a === normalize(artist) || a.includes(normalize(artist)))) score += 40;
  }
  return score + (candidate.popularity ?? 0) / 100; // tie-break by popularity
}

/** Search with Spotify's field filters, then pick the best match (not blindly the first). */
async function findItem(title, artist, kind) {
  const quote = (s) => s.replace(/"/g, "");
  const filtered =
    kind === "track"
      ? `track:"${quote(title)}"${artist ? ` artist:"${quote(artist)}"` : ""}`
      : kind === "album"
        ? `album:"${quote(title)}"${artist ? ` artist:"${quote(artist)}"` : ""}`
        : `${title}${artist ? ` ${artist}` : ""}`;
  const queries = [filtered, `${title} ${artist}`.trim()];
  for (const q of queries) {
    const search = await spotifyApi("GET", `/search?${new URLSearchParams({ q, type: kind, limit: "10" })}`);
    if (search.notConnected) return { notConnected: true };
    const items = search.data?.[`${kind}s`]?.items?.filter(Boolean) ?? [];
    if (items.length === 0) continue;
    const ranked = items.map((it) => ({ it, score: matchScore(it, title, artist) })).sort((a, b) => b.score - a.score);
    // A filtered search is trusted; the free-text fallback must at least resemble the title.
    if (q === filtered || ranked[0].score >= 30) return { item: ranked[0].it };
  }
  return { item: null };
}

async function play({ query, artist, kind }) {
  const search = await findItem(query, artist, kind);
  if (search.notConnected) {
    await shell.openExternal(`spotify:search:${encodeURIComponent(`${query} ${artist}`.trim())}`);
    return {
      status: "partial",
      message: "Spotify no está conectado a Isabel: abrí la búsqueda en Spotify para que el usuario elija. " +
        "Para reproducir directamente, conecta Spotify en Ajustes → Spotify.",
    };
  }
  const item = search.item;
  if (!item) return { status: "not_found", message: `No encontré «${query}»${artist ? ` de ${artist}` : ""} en Spotify.` };
  const body = kind === "track" ? { uris: [item.uri] } : { context_uri: item.uri };
  const label = kind === "track" ? describeItem(item) : item.name;

  // Always play on THIS computer. Without a device id, Spotify plays on the account's
  // "active device", which may be the user's phone: it then says OK and nothing sounds here.
  let device = await localDevice();
  if (!device) {
    await shell.openExternal("spotify:"); // open the desktop app and wait for it to register
    for (let i = 0; i < 12 && !device; i++) {
      await sleep(1000);
      device = await localDevice();
    }
  }
  if (!device) return { status: "error", message: "No encontré Spotify abierto en este PC. Ábrelo e inténtalo otra vez." };

  // What works with the Windows desktop app (measured): first transfer playback to it WITH
  // play (this wakes its player; a bare "play" is accepted with 204 but ignored when the
  // player is empty), then play a context — for a song, its album positioned on that song.
  await spotifyApi("PUT", "/me/player", { device_ids: [device.id], play: true });
  await sleep(1500);
  const target = `/me/player/play?device_id=${encodeURIComponent(device.id)}`;
  const playBody = kind === "track" ? { context_uri: item.album.uri, offset: { uri: item.uri } } : body;
  let result = await spotifyApi("PUT", target, playBody);
  if (!result.ok && kind === "track") result = await spotifyApi("PUT", target, body); // single track
  if (result.status === 403) return { status: "error", message: "Spotify no permite controlar la reproducción (se necesita Premium)." };
  if (!result.ok) return { status: "error", message: `Spotify respondió ${result.status}.` };

  // Check that it really plays here before saying so. The desktop app can take several
  // seconds to start, and the Web API reports its state even later, so two sources are
  // checked: the API, and Spotify's window title ("Artist - Song" = what is playing now).
  const started = Date.now();
  while (Date.now() - started < PLAY_CONFIRM_MS) {
    await sleep(900);
    const title = (await spotifyWindowTitle()) ?? "";
    if (kind === "track" && titleMatches(title, item)) return { status: "ok", playing: label, kind, device: device.name };
    const player = (await spotifyApi("GET", "/me/player")).data;
    const here = player?.device?.id === device.id;
    const same = kind === "track" ? player?.item?.uri === item.uri : player?.context?.uri === item.uri;
    if (here && same && player?.is_playing) return { status: "ok", playing: label, kind, device: device.name };
    // A collection (artist/album/playlist) is playing as soon as the title shows any song.
    if (kind !== "track" && title && !/^spotify/i.test(title) && Date.now() - started > 2500) {
      return { status: "ok", playing: label, kind, device: device.name, now: title };
    }
  }
  return {
    status: "unconfirmed",
    message: `Le pedí a Spotify que ponga «${label}» en este PC (${device.name}), pero todavía no la veo sonar. ` +
      "Tell the user it may take a few more seconds, or to press play in Spotify if it does not start.",
  };
}

const PLAY_CONFIRM_MS = 12_000; // the desktop app took ~6 s to start in testing

const normalize = (text) =>
  text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, " ").trim();

/** Spotify's window title is "Artist - Song" while playing. */
function titleMatches(title, item) {
  const t = normalize(title);
  return Boolean(t) && t.includes(normalize(item.name).slice(0, 40));
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** The Spotify desktop app on this computer, from the account's device list. */
async function localDevice() {
  const devices = (await spotifyApi("GET", "/me/player/devices")).data?.devices ?? [];
  const computers = devices.filter((d) => d.type === "Computer" && !d.is_restricted);
  const host = os.hostname().toLowerCase();
  return (
    computers.find((d) => d.name.toLowerCase() === host) ??
    computers.find((d) => d.name.toLowerCase().includes(host) || host.includes(d.name.toLowerCase())) ??
    (computers.length === 1 ? computers[0] : computers.find((d) => d.is_active)) ??
    null
  );
}

/** Run one agent tool on this computer; always resolves to a small JSON result. */
async function runAction(tool, args) {
  try {
    if (tool === "media_control") return await pressMediaKey(args?.action);
    if (tool === "now_playing") return await nowPlaying();
    if (tool === "spotify_play") {
      const kind = ["track", "artist", "album", "playlist"].includes(args?.kind) ? args.kind : "track";
      const query = String(args?.query ?? "").slice(0, 200).trim();
      const artist = String(args?.artist ?? "").slice(0, 100).trim();
      if (!query) return { status: "error", error: "Empty query" };
      return await play({ query, artist, kind });
    }
    return { status: "error", error: `Unknown computer action ${tool}` };
  } catch (error) {
    return { status: "error", error: `The action failed: ${error.message}` };
  }
}

/** Read-only diagnostics for troubleshooting (electron . --spotify-diagnose). Plays nothing. */
async function diagnose() {
  const out = { connected: (await status()).connected, hostname: os.hostname() };
  try {
    out.token = Boolean(await getAccessToken());
  } catch (error) {
    out.token = `error: ${error.message}`;
  }
  const devices = await spotifyApi("GET", "/me/player/devices");
  out.devicesStatus = devices.status ?? (devices.notConnected ? "not connected" : "?");
  out.devices = (devices.data?.devices ?? []).map((d) => ({
    name: d.name,
    type: d.type,
    active: d.is_active,
    restricted: d.is_restricted,
  }));
  const player = await spotifyApi("GET", "/me/player");
  out.playerStatus = player.status;
  out.player = player.data
    ? { device: player.data.device?.name, playing: player.data.is_playing, item: describeItem(player.data.item) }
    : null;
  out.localDevice = (await localDevice())?.name ?? null;
  out.window = await spotifyWindowTitle();
  return out;
}

module.exports = { runAction, connect, status, disconnect, diagnose, REDIRECT_URI };
