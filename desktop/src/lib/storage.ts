// Preferences persistence: a JSON file in the user's profile when running in Electron,
// localStorage in a plain browser. Always falls back to the defaults.

import { type AppSettings, DEFAULT_SETTINGS, sanitizeSettings } from "../orb/settings";

const LOCAL_KEY = "assistant.settings";
const THREAD_KEY = "assistant.thread";

export async function loadSettings(): Promise<AppSettings> {
  try {
    if (window.assistant) return sanitizeSettings(await window.assistant.loadSettings());
    const raw = localStorage.getItem(LOCAL_KEY);
    return sanitizeSettings(raw ? JSON.parse(raw) : null);
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export async function saveSettings(settings: AppSettings): Promise<void> {
  try {
    if (window.assistant) await window.assistant.saveSettings(settings);
    else localStorage.setItem(LOCAL_KEY, JSON.stringify(settings));
  } catch {
    // Preferences are a convenience: never break the app over them.
  }
}

export function loadThreadId(): string | null {
  try {
    return localStorage.getItem(THREAD_KEY);
  } catch {
    return null;
  }
}

export function saveThreadId(id: string | null) {
  try {
    if (id) localStorage.setItem(THREAD_KEY, id);
    else localStorage.removeItem(THREAD_KEY);
  } catch {
    // ignore
  }
}
