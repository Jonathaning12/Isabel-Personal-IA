import { type CSSProperties, type ReactNode, useEffect, useState } from "react";
import type { OrbState } from "../orb/OrbEngine";
import { api } from "../api";
import { type AppSettings, DEFAULT_ORB, NATURAL_VOICES, type OrbSettings, PRESETS } from "../orb/settings";
import { SHAPES } from "../orb/shapes";
import { saveSettings } from "../lib/storage";
import { loadVoices, playSpeech } from "../voice/speech";
import type { WakeEngine, WakeState } from "../voice/useWakeWord";
import { CloseIcon } from "./Icons";
import { GoogleSettings } from "./GoogleSettings";
import { MorningSettings } from "./MorningSettings";

interface Props {
  open: boolean;
  settings: AppSettings;
  /** Material the window is currently using (null outside Electron). */
  activeMaterial: "glass" | "acrylic" | null;
  wakeStatus: WakeState;
  wakeEngine: WakeEngine;
  preview: OrbState | null;
  onChange: (settings: AppSettings) => void;
  onPreview: (state: OrbState | null) => void;
  onClose: () => void;
}

const PREVIEWS: { state: OrbState; label: string }[] = [
  { state: "idle", label: "Reposo" },
  { state: "gathering", label: "Recopilando" },
  { state: "thinking", label: "Pensando" },
  { state: "speaking", label: "Hablando" },
  { state: "listening", label: "Escuchando" },
  { state: "alert", label: "Aprobación" },
];

const MATERIALS: { id: AppSettings["backgroundMaterial"]; label: string; hint: string }[] = [
  { id: "glass", label: "Vidrio nítido", hint: "Ventana totalmente transparente: se ve el escritorio tal cual" },
  { id: "acrylic", label: "Acrílico difuminado", hint: "Windows difumina lo que hay detrás de la ventana" },
];

const WAKE_HINTS: Record<WakeState, string> = {
  off: "Desactivado. También puedes hablar con el botón del micrófono.",
  loading: "Cargando el reconocedor local…",
  ready: "Se detecta en tu PC, sin internet. El audio solo se envía para transcribir lo que dices después de «Isabel».",
  unavailable: "Falta el modelo de voz local. Ejecuta `npm run fetch-model` en la carpeta desktop y reinicia la app.",
  error: "No se pudo iniciar la detección (¿micrófono ocupado o sin permiso?).",
};

type NumberKey = { [K in keyof OrbSettings]: OrbSettings[K] extends number ? K : never }[keyof OrbSettings];
type ColorKey = Extract<keyof OrbSettings, `color${string}`>;

const COLORS: { key: ColorKey; label: string }[] = [
  { key: "colorPrimary", label: "Principal" },
  { key: "colorSecondary", label: "Secundario" },
  { key: "colorThinking", label: "Pensando" },
  { key: "colorGathering", label: "Recopilando" },
  { key: "colorSpeaking", label: "Hablando" },
  { key: "colorListening", label: "Escuchando" },
];

const REACTIONS: { key: NumberKey; label: string }[] = [
  { key: "breathing", label: "Respiración" },
  { key: "hover", label: "Al pasar el puntero" },
  { key: "thinking", label: "Pensando" },
  { key: "gathering", label: "Recopilando" },
  { key: "speaking", label: "Hablando" },
  { key: "listening", label: "Escuchando" },
  { key: "burst", label: "Clic (estallido)" },
];

/** Right-hand drawer to customize every part of the orb, plus voice preferences. */
export function SettingsPanel({ open, settings, activeMaterial, wakeStatus, wakeEngine, preview, onChange, onPreview, onClose }: Props) {
  const orb = settings.orb;
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  useEffect(() => {
    void loadVoices().then(setVoices);
  }, []);

  const [testing, setTesting] = useState(false);
  const testVoice = async () => {
    setTesting(true);
    try {
      const wav = await api.speech("Hola, soy Isabel. Así sueno con esta voz. ¿Te gusta?", settings.naturalVoice);
      setTesting(false);
      await playSpeech(wav, () => undefined);
    } catch {
      setTesting(false);
    }
  };

  const setOrb = (patch: Partial<OrbSettings>) => onChange({ ...settings, orb: { ...orb, ...patch } });

  const slider = (key: NumberKey, label: string, min: number, max: number, step: number, format?: (v: number) => string) => (
    <label className="control" key={key}>
      <span className="control__label">
        {label}
        <output>{format ? format(orb[key]) : orb[key] === 0 ? "off" : orb[key].toFixed(step < 1 ? 2 : 0)}</output>
      </span>
      <input type="range" min={min} max={max} step={step} value={orb[key]} onChange={(e) => setOrb({ [key]: Number(e.target.value) })} />
    </label>
  );

  return (
    <aside className={`settings ${open ? "settings--open" : ""}`} aria-hidden={!open} inert={!open} aria-label="Personalizar la burbuja">
      <header className="settings__header">
        <h2>Personalizar</h2>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Cerrar ajustes">
          <CloseIcon />
        </button>
      </header>

      <div className="settings__body">
        <Section title="Vista previa de estados">
          <div className="chips">
            {PREVIEWS.map((p) => (
              <button
                key={p.state}
                type="button"
                className={`chip ${preview === p.state ? "chip--active" : ""}`}
                onClick={() => onPreview(preview === p.state ? null : p.state)}
              >
                {p.label}
              </button>
            ))}
          </div>
          {preview ? <p className="hint">Vista previa activa. Pulsa el estado otra vez para volver al real.</p> : null}
        </Section>

        <Section title="Estilos">
          <div className="chips">
            {PRESETS.map((p) => (
              <button
                key={p.name}
                type="button"
                className="chip chip--preset"
                style={{ "--a": p.orb.colorPrimary ?? DEFAULT_ORB.colorPrimary, "--b": p.orb.colorSecondary ?? DEFAULT_ORB.colorSecondary } as CSSProperties}
                onClick={() => setOrb({ ...DEFAULT_ORB, particleCount: orb.particleCount, ...p.orb })}
              >
                <span className="chip__swatch" />
                {p.name}
              </button>
            ))}
          </div>
        </Section>

        <Section title="Forma">
          <div className="chips">
            {SHAPES.map((s) => (
              <button key={s.id} type="button" className={`chip ${orb.shape === s.id ? "chip--active" : ""}`} onClick={() => setOrb({ shape: s.id })}>
                {s.label}
              </button>
            ))}
          </div>
          {slider("size", "Tamaño", 0.5, 1.6, 0.05)}
        </Section>

        <Section title="Partículas">
          {slider("particleCount", "Cantidad", 2000, 30000, 1000, (v) => `${Math.round(v / 1000)}k`)}
          {slider("particleSize", "Tamaño de partícula", 0.4, 3, 0.05)}
          {slider("glow", "Brillo", 0, 1, 0.05)}
        </Section>

        <Section title="Colores">
          <div className="colors">
            {COLORS.map((c) => (
              <label key={c.key} className="color">
                <input type="color" value={orb[c.key]} onChange={(e) => setOrb({ [c.key]: e.target.value })} />
                <span>{c.label}</span>
              </label>
            ))}
          </div>
        </Section>

        <Section title="Movimiento">
          {slider("speed", "Velocidad general", 0.2, 3, 0.05)}
          {slider("rotation", "Rotación", 0, 2, 0.05)}
          {slider("turbulence", "Turbulencia", 0, 1, 0.05)}
          <label className="toggle">
            <input type="checkbox" checked={orb.ambientDust} onChange={(e) => setOrb({ ambientDust: e.target.checked })} />
            <span>Polvo de fondo</span>
          </label>
        </Section>

        <Section title="Fondo">
          <div className="chips">
            {MATERIALS.map((m) => (
              <button
                key={m.id}
                type="button"
                className={`chip ${settings.backgroundMaterial === m.id ? "chip--active" : ""}`}
                onClick={() => onChange({ ...settings, backgroundMaterial: m.id })}
                title={m.hint}
              >
                {m.label}
              </button>
            ))}
          </div>
          {activeMaterial && activeMaterial !== settings.backgroundMaterial ? (
            <p className="hint">
              Se aplica al reiniciar la app.{" "}
              <button
                type="button"
                className="link-button"
                onClick={async () => {
                  await saveSettings(settings);
                  await window.assistant?.relaunch();
                }}
              >
                Reiniciar ahora
              </button>
            </p>
          ) : null}
          <label className="control">
            <span className="control__label">
              Oscuridad del cristal
              <output>{Math.round(settings.backgroundOpacity * 100)}%</output>
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.02}
              value={settings.backgroundOpacity}
              onChange={(e) => onChange({ ...settings, backgroundOpacity: Number(e.target.value) })}
            />
          </label>
          <p className="hint">0% = vidrio totalmente claro; 100% = negro sólido.</p>
        </Section>

        <Section title="Intensidad de cada reacción">{REACTIONS.map((r) => slider(r.key, r.label, 0, 1.5, 0.05))}</Section>

        <Section title="Voz">
          <label className="toggle">
            <input type="checkbox" checked={settings.wakeWord} onChange={(e) => onChange({ ...settings, wakeWord: e.target.checked })} />
            <span>Activar diciendo «Isabel»</span>
          </label>
          <p className="hint">{WAKE_HINTS[wakeStatus]}</p>
          {wakeStatus === "ready" ? (
            <p className="hint">
              {wakeEngine === "trained"
                ? "Detector de «Isabel»: modelo entrenado (openWakeWord), el más preciso."
                : "Detector de «Isabel»: básico (Vosk). Para uno más preciso, entrena tu modelo: services/voice/TRAINING.md."}
            </p>
          ) : null}
          <label className="toggle">
            <input type="checkbox" checked={settings.voiceReplies} onChange={(e) => onChange({ ...settings, voiceReplies: e.target.checked })} />
            <span>Responder en voz alta</span>
          </label>
          <div className="chips">
            <button
              type="button"
              className={`chip ${settings.voiceEngine === "natural" ? "chip--active" : ""}`}
              onClick={() => onChange({ ...settings, voiceEngine: "natural" })}
            >
              Voz natural
            </button>
            <button
              type="button"
              className={`chip ${settings.voiceEngine === "system" ? "chip--active" : ""}`}
              onClick={() => onChange({ ...settings, voiceEngine: "system" })}
            >
              Voz de Windows
            </button>
          </div>
          {settings.voiceEngine === "natural" ? (
            <>
              <label className="control">
                <span className="control__label">Voz natural (Gemini)</span>
                <select value={settings.naturalVoice} onChange={(e) => onChange({ ...settings, naturalVoice: e.target.value })}>
                  {NATURAL_VOICES.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className="button button--ghost button--block" onClick={() => void testVoice()} disabled={testing}>
                {testing ? "Generando…" : "Probar esta voz"}
              </button>
              <p className="hint">
                Suena humana y suave. Si se acaba la cuota gratis de Gemini, habla una voz local (Piper) y, como último recurso, la
                de Windows.
              </p>
            </>
          ) : null}
          <label className="control" hidden={settings.voiceEngine === "natural"}>
            <span className="control__label">Voz de Windows</span>
            <select
              value={settings.voiceName ?? ""}
              onChange={(e) => onChange({ ...settings, voiceName: e.target.value || null })}
              disabled={voices.length === 0}
            >
              <option value="">{voices.length ? "Automática (español)" : "No hay voces en español"}</option>
              {voices.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
        </Section>

        {window.assistant ? (
          <Section title="Aplicación">
            <label className="control">
              <span className="control__label">Tu nombre</span>
              <input
                className="text-input"
                value={settings.userName}
                maxLength={40}
                onChange={(e) => onChange({ ...settings, userName: e.target.value })}
                placeholder="Para saludarte y en los recordatorios"
              />
            </label>
            <MorningSettings />
            <label className="toggle">
              <input
                type="checkbox"
                checked={settings.startWithWindows}
                onChange={(e) => onChange({ ...settings, startWithWindows: e.target.checked })}
              />
              <span>Abrir Isabel al iniciar Windows (en la bandeja)</span>
            </label>
            <label className="toggle">
              <input type="checkbox" checked={settings.closeToTray} onChange={(e) => onChange({ ...settings, closeToTray: e.target.checked })} />
              <span>Al cerrar, seguir en la bandeja del sistema</span>
            </label>
            <p className="hint">
              Así los recordatorios y «Isabel» siguen funcionando con la ventana cerrada. Para salir del todo: icono de la
              bandeja → Salir.
            </p>
            <label className="toggle">
              <input type="checkbox" checked={settings.statusBar} onChange={(e) => onChange({ ...settings, statusBar: e.target.checked })} />
              <span>Barra de estado arriba de la pantalla</span>
            </label>
            <p className="hint">
              Con la ventana minimizada o en la bandeja, una barra pequeña muestra si Isabel te escucha, piensa o habla, con
              botones para silenciar el micrófono y escribirle.
            </p>
          </Section>
        ) : null}

        {window.assistant ? <SpotifySection /> : null}
        {window.assistant ? (
          <Section title="Google: calendario y correo">
            <GoogleSettings />
          </Section>
        ) : null}

        <button type="button" className="button button--ghost button--block" onClick={() => setOrb(DEFAULT_ORB)}>
          Restablecer la burbuja
        </button>
      </div>
    </aside>
  );
}

/** Connect Isabel to the user's Spotify (official Web API, OAuth PKCE; Premium needed to play). */
function SpotifySection() {
  const [status, setStatus] = useState<{ connected: boolean; clientId: string } | null>(null);
  const [clientId, setClientId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    void window.assistant?.spotifyStatus().then((s) => {
      setStatus(s);
      if (s?.clientId) setClientId(s.clientId);
    });
  }, []);

  const connect = async () => {
    setBusy(true);
    setMessage("Se abrió el navegador: inicia sesión en Spotify y acepta los permisos.");
    const result = await window.assistant!.spotifyConnect(clientId);
    setBusy(false);
    setMessage(result.ok ? "¡Conectado! Prueba: «Isabel, pon Bohemian Rhapsody»." : (result.error ?? "No se pudo conectar."));
    setStatus(await window.assistant!.spotifyStatus());
  };

  const disconnect = async () => {
    await window.assistant!.spotifyDisconnect();
    setStatus(await window.assistant!.spotifyStatus());
    setMessage("Desconectado.");
  };

  return (
    <Section title="Spotify">
      <p className="hint">
        Sin conectar, Isabel ya puede pausar, cambiar de canción, subir o bajar el volumen y decirte qué suena. Para
        que ponga canciones concretas, conecta tu cuenta Premium:
      </p>
      {status?.connected ? (
        <>
          <p className="hint spotify-ok">● Conectada a Spotify</p>
          <button type="button" className="button button--ghost button--block" onClick={() => void disconnect()}>
            Desconectar Spotify
          </button>
        </>
      ) : (
        <>
          <ol className="hint spotify-steps">
            <li>Entra en developer.spotify.com/dashboard y crea una app (gratis).</li>
            <li>
              Redirect URI: <code>http://127.0.0.1:8888/callback</code> · API: Web API.
            </li>
            <li>Copia el Client ID y pégalo aquí.</li>
          </ol>
          <label className="control">
            <span className="control__label">Client ID</span>
            <input
              className="text-input"
              value={clientId}
              onChange={(e) => setClientId(e.target.value.trim())}
              placeholder="32 caracteres"
              spellCheck={false}
            />
          </label>
          <button
            type="button"
            className="button button--primary button--block"
            onClick={() => void connect()}
            disabled={busy || clientId.length !== 32}
          >
            {busy ? "Esperando a Spotify…" : "Conectar con Spotify"}
          </button>
        </>
      )}
      {message ? <p className="hint">{message}</p> : null}
    </Section>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="settings__section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}
