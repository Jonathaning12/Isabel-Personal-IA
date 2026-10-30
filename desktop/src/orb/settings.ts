// Everything the user can tune about the orb, with defaults and presets.

import type { ShapeId } from "./shapes";

export interface OrbSettings {
  shape: ShapeId;
  size: number; // overall scale, 0.5–1.6
  particleCount: number; // 2 000–30 000
  particleSize: number; // 0.4–3
  colorPrimary: string;
  colorSecondary: string;
  colorThinking: string;
  colorGathering: string;
  colorSpeaking: string;
  colorListening: string;
  glow: number; // 0–1, halo and particle brightness
  speed: number; // global animation speed, 0.2–3
  rotation: number; // idle rotation speed, 0–2
  turbulence: number; // organic noise, 0–1
  // Strength of each reaction, 0 (off) – 1.5
  breathing: number;
  hover: number;
  thinking: number;
  gathering: number;
  speaking: number;
  listening: number;
  burst: number; // click reaction
  ambientDust: boolean; // slow particles in the background
}

export interface AppSettings {
  /** Bumped when a default changes and saved values should be migrated. */
  version: number;
  orb: OrbSettings;
  /** Darkness of the tint over the desktop, 0 (clear glass) – 1 (solid black). */
  backgroundOpacity: number;
  /** "glass": sharp, fully transparent window; "acrylic": Windows blurs what is behind. */
  backgroundMaterial: "glass" | "acrylic";
  voiceReplies: boolean;
  voiceName: string | null;
  sidebarOpen: boolean;
  /** Listen locally for "Isabel" to start a voice command. */
  wakeWord: boolean;
  /** "natural": Gemini voices (soft, human); "system": the operating system's voices. */
  voiceEngine: "natural" | "system";
  naturalVoice: string;
  /** Project folder (relative to the projects folder) used for "esta carpeta". */
  currentProject: string | null;
  /** Closing the window keeps Isabel running in the tray (reminders, "Isabel"). */
  closeToTray: boolean;
}

/** Natural voices offered in the settings (Gemini prebuilt voices). */
export const NATURAL_VOICES: { id: string; label: string }[] = [
  { id: "Achernar", label: "Achernar · suave" },
  { id: "Sulafat", label: "Sulafat · cálida" },
  { id: "Vindemiatrix", label: "Vindemiatrix · amable" },
  { id: "Despina", label: "Despina · fluida" },
  { id: "Aoede", label: "Aoede · ligera" },
  { id: "Leda", label: "Leda · juvenil" },
  { id: "Kore", label: "Kore · firme" },
  { id: "Charon", label: "Charon · masculina" },
];

export const DEFAULT_ORB: OrbSettings = {
  shape: "sphere",
  size: 1,
  particleCount: 14000,
  particleSize: 1.2,
  colorPrimary: "#5ad1ff",
  colorSecondary: "#7a5cff",
  colorThinking: "#b18cff",
  colorGathering: "#4dffc3",
  colorSpeaking: "#8fe3ff",
  colorListening: "#ff7ad9",
  glow: 0.6,
  speed: 1,
  rotation: 0.6,
  turbulence: 0.45,
  breathing: 1,
  hover: 0.1,
  thinking: 1,
  gathering: 1,
  speaking: 1,
  listening: 1,
  burst: 1,
  ambientDust: true,
};

export const PRESETS: { name: string; orb: Partial<OrbSettings> }[] = [
  { name: "Núcleo", orb: {} },
  {
    name: "Plasma",
    orb: {
      colorPrimary: "#ff4d8d",
      colorSecondary: "#ffb347",
      colorThinking: "#ff3b3b",
      colorGathering: "#ffd36e",
      colorSpeaking: "#ff8fb8",
      colorListening: "#ffe08a",
      turbulence: 0.7,
      glow: 0.75,
    },
  },
  {
    name: "Aurora",
    orb: {
      shape: "galaxy",
      colorPrimary: "#3dffa8",
      colorSecondary: "#2f7bff",
      colorThinking: "#9b6bff",
      colorGathering: "#c6ff4d",
      colorSpeaking: "#6be6ff",
      colorListening: "#ff6bd6",
      rotation: 0.9,
    },
  },
  {
    name: "Ámbar",
    orb: {
      shape: "torus",
      colorPrimary: "#ffb340",
      colorSecondary: "#ff5e3a",
      colorThinking: "#ffd27a",
      colorGathering: "#ffe9b0",
      colorSpeaking: "#ffc46b",
      colorListening: "#ff8a5c",
      glow: 0.5,
    },
  },
  {
    name: "Monocromo",
    orb: {
      colorPrimary: "#e8ecf2",
      colorSecondary: "#5d6370",
      colorThinking: "#ffffff",
      colorGathering: "#b9c2d0",
      colorSpeaking: "#ffffff",
      colorListening: "#d0d6df",
      glow: 0.35,
      turbulence: 0.3,
    },
  },
];

// v2: lighter "sunglass lens" background (0.62 → 0.36). v3: subtler hover (1 → 0.1).
// v4: almost clear glass (0.36 → 0.12). v5: transparent "glass" window, no tint.
// v6: glass tint 0 → 0.2. v7: 0.2 → 0.3. v8: 0.3 → 0.5. v9: 0.5 → 0.6.
export const SETTINGS_VERSION = 9;

export const DEFAULT_SETTINGS: AppSettings = {
  version: SETTINGS_VERSION,
  orb: DEFAULT_ORB,
  backgroundOpacity: 0.6,
  backgroundMaterial: "glass",
  voiceReplies: true,
  voiceName: null,
  sidebarOpen: false,
  wakeWord: true,
  voiceEngine: "natural",
  naturalVoice: "Achernar",
  currentProject: null,
  closeToTray: true,
};

const clamp = (v: unknown, min: number, max: number, fallback: number) =>
  typeof v === "number" && Number.isFinite(v) ? Math.min(max, Math.max(min, v)) : fallback;

const isColor = (v: unknown): v is string => typeof v === "string" && /^#[0-9a-f]{6}$/i.test(v);

/** Merge saved settings over the defaults, dropping anything invalid. */
export function sanitizeSettings(raw: unknown): AppSettings {
  const saved = (raw && typeof raw === "object" ? raw : {}) as Partial<AppSettings>;
  const o = (saved.orb && typeof saved.orb === "object" ? saved.orb : {}) as Partial<OrbSettings>;
  const d = DEFAULT_ORB;
  const shapes: ShapeId[] = ["sphere", "torus", "cube", "galaxy", "helix", "cloud"];
  const color = (key: keyof OrbSettings) => (isColor(o[key]) ? (o[key] as string) : (d[key] as string));
  const amount = (key: keyof OrbSettings) => clamp(o[key], 0, 1.5, d[key] as number);
  const savedVersion = typeof saved.version === "number" ? saved.version : 1;
  return {
    orb: {
      shape: shapes.includes(o.shape as ShapeId) ? (o.shape as ShapeId) : d.shape,
      size: clamp(o.size, 0.5, 1.6, d.size),
      particleCount: Math.round(clamp(o.particleCount, 2000, 30000, d.particleCount)),
      particleSize: clamp(o.particleSize, 0.4, 3, d.particleSize),
      colorPrimary: color("colorPrimary"),
      colorSecondary: color("colorSecondary"),
      colorThinking: color("colorThinking"),
      colorGathering: color("colorGathering"),
      colorSpeaking: color("colorSpeaking"),
      colorListening: color("colorListening"),
      glow: clamp(o.glow, 0, 1, d.glow),
      speed: clamp(o.speed, 0.2, 3, d.speed),
      rotation: clamp(o.rotation, 0, 2, d.rotation),
      turbulence: clamp(o.turbulence, 0, 1, d.turbulence),
      breathing: amount("breathing"),
      hover: savedVersion >= 3 ? amount("hover") : d.hover,
      thinking: amount("thinking"),
      gathering: amount("gathering"),
      speaking: amount("speaking"),
      listening: amount("listening"),
      burst: amount("burst"),
      ambientDust: typeof o.ambientDust === "boolean" ? o.ambientDust : d.ambientDust,
    },
    version: SETTINGS_VERSION,
    // Older saved settings keep everything except the defaults that changed since.
    backgroundOpacity:
      savedVersion >= 9
        ? clamp(saved.backgroundOpacity, 0, 1, DEFAULT_SETTINGS.backgroundOpacity)
        : DEFAULT_SETTINGS.backgroundOpacity,
    backgroundMaterial:
      savedVersion >= 5 && saved.backgroundMaterial === "acrylic" ? "acrylic" : DEFAULT_SETTINGS.backgroundMaterial,
    voiceReplies: typeof saved.voiceReplies === "boolean" ? saved.voiceReplies : true,
    voiceName: typeof saved.voiceName === "string" ? saved.voiceName : null,
    sidebarOpen: typeof saved.sidebarOpen === "boolean" ? saved.sidebarOpen : false,
    wakeWord: typeof saved.wakeWord === "boolean" ? saved.wakeWord : true,
    voiceEngine: saved.voiceEngine === "system" ? "system" : "natural",
    currentProject:
      typeof saved.currentProject === "string" && saved.currentProject.length < 200 ? saved.currentProject : null,
    closeToTray: typeof saved.closeToTray === "boolean" ? saved.closeToTray : true,
    naturalVoice: NATURAL_VOICES.some((v) => v.id === saved.naturalVoice)
      ? (saved.naturalVoice as string)
      : DEFAULT_SETTINGS.naturalVoice,
  };
}
