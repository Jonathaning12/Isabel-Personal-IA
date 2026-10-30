import { type CSSProperties, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type VaultInfo, api, isDesktop } from "./api";
import { AnswerView } from "./components/AnswerView";
import { ApprovalCard } from "./components/ApprovalCard";
import { Banner } from "./components/Banner";
import { CloseIcon, EarIcon, FolderIcon, MaximizeIcon, MicIcon, MicOffIcon, MinimizeIcon, MuteIcon, PanelIcon, SpeakerIcon, TuneIcon } from "./components/Icons";
import { SettingsPanel } from "./components/SettingsPanel";
import { VoiceGlow } from "./components/VoiceGlow";
import { Sidebar } from "./components/Sidebar";
import { STATUS_LABELS } from "./lib/labels";
import { loadSettings, saveSettings } from "./lib/storage";
import type { OrbState } from "./orb/OrbEngine";
import { ParticleOrb } from "./orb/ParticleOrb";
import { type AppSettings, DEFAULT_SETTINGS } from "./orb/settings";
import { useAssistant } from "./useAssistant";
import { useWakeWord } from "./voice/useWakeWord";

type Connection = "checking" | "online" | "offline";

export function App() {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [loaded, setLoaded] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [preview, setPreview] = useState<OrbState | null>(null);
  const [hovering, setHovering] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [connection, setConnection] = useState<Connection>("checking");
  const [model, setModel] = useState<string>("");
  const [vault, setVault] = useState<VaultInfo | null>(null);
  const loadVault = useCallback(() => {
    api.vault().then(setVault, () => setVault(null));
  }, []);
  const saveTimer = useRef<number | undefined>(undefined);
  // Material the window was actually created with (it only changes on restart).
  const [windowInfo, setWindowInfo] = useState<{ customControls: boolean; material: "glass" | "acrylic" } | null>(null);

  useEffect(() => {
    void window.assistant?.windowInfo().then(setWindowInfo);
  }, []);

  const assistant = useAssistant({
    voiceReplies: settings.voiceReplies,
    voiceName: settings.voiceName,
    voiceEngine: settings.voiceEngine,
    naturalVoice: settings.naturalVoice,
    project: settings.currentProject,
    onDataChanged: () => setRefreshKey((k) => k + 1),
  });
  const [pulseKey, setPulseKey] = useState(0);
  // Local listening: "Isabel" while idle; "sí / no" while an approval waits (after she has
  // finished reading it aloud); nothing while she records, thinks or speaks.
  const wakeIdle = (assistant.phase === "idle" || assistant.phase === "error") && !assistant.pending;
  const listenMode = assistant.pending && !assistant.askingAloud ? "confirm" : wakeIdle ? "wake" : "off";
  const wakeStatus = useWakeWord(loaded && settings.wakeWord, listenMode, {
    onWake: (preroll) => {
      setPulseKey((k) => k + 1); // the orb reacts to her name
      assistant.wake(preroll);
    },
    onConfirm: (decision) => {
      assistant.log({ kind: "voice", title: decision === "approve" ? "Dijiste «sí»" : "Dijiste «no»" });
      void assistant.decide(decision);
    },
  });

  useEffect(() => {
    void loadSettings().then((s) => {
      setSettings(s);
      setLoaded(true);
    });
  }, []);

  // Save preferences shortly after the last change (sliders fire many events).
  const update = useCallback((next: AppSettings) => {
    setSettings(next);
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => void saveSettings(next), 400);
  }, []);

  const checkHealth = useCallback(async () => {
    try {
      const health = await api.health();
      setConnection((previous) => {
        if (previous !== "online") loadVault(); // (re)connected: refresh vault info
        return "online";
      });
      setModel(health.models.llm);
    } catch (error) {
      // A 503 still means the API is up (the AI provider is the one failing).
      setConnection(error instanceof ApiError && error.status === 503 ? "online" : "offline");
    }
  }, [loadVault]);

  useEffect(() => {
    void checkHealth();
    const timer = window.setInterval(() => void checkHealth(), 15000);
    return () => window.clearInterval(timer);
  }, [checkHealth]);

  // Reminders come from the main process (also while the window is in the tray).
  const { announce, log, setNotice: showNotice } = assistant;
  useEffect(() => {
    const unsubscribe = window.assistant?.onReminder(({ text }) => {
      setPulseKey((k) => k + 1);
      showNotice(`⏰ Recordatorio: ${text}`);
      log({ kind: "message", title: "Recordatorio", detail: text, status: "warn" });
      void announce(`Recordatorio: ${text}`);
    });
    return unsubscribe;
  }, [announce, log, showNotice]);

  // Hide the notice after a while.
  const { notice, setNotice } = assistant;
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(timer);
  }, [notice, setNotice]);

  const toggleSidebar = () => update({ ...settings, sidebarOpen: !settings.sidebarOpen });
  const orbState = preview ?? assistant.orbState;
  const status = preview ? `Vista previa · ${STATUS_LABELS[previewPhase(preview)]}` : STATUS_LABELS[assistant.phase];
  // In a plain browser there is no blurred desktop behind the page: keep it solid.
  const tint = isDesktop() ? settings.backgroundOpacity : 1;
  const accent = {
    "--accent": settings.orb.colorPrimary,
    "--accent-2": settings.orb.colorSecondary,
    "--tint": tint,
    "--listen": settings.orb.colorListening,
  } as CSSProperties;

  return (
    <div
      className={`app ${settings.sidebarOpen ? "app--sidebar" : ""} ${settingsOpen ? "app--settings" : ""} ${hovering ? "app--hover" : ""} ${windowInfo?.material === "glass" ? "app--glass" : ""}`}
      style={accent}
    >
      <header className={`topbar ${windowInfo?.customControls ? "topbar--custom" : ""}`}>
        <button
          type="button"
          className={`icon-button ${settings.sidebarOpen ? "icon-button--active" : ""}`}
          onClick={toggleSidebar}
          aria-label={settings.sidebarOpen ? "Ocultar panel" : "Mostrar panel"}
          title="Panel"
        >
          <PanelIcon />
        </button>
        <span className="brand">Isabel</span>
        <div className={`connection connection--${connection}`} title={model ? `Modelo: ${model}` : undefined}>
          <span className="connection__dot" />
          {connection === "online" ? "En línea" : connection === "offline" ? "Sin conexión con el asistente" : "Conectando…"}
        </div>
        {settings.currentProject ? (
          <button
            type="button"
            className="project-chip"
            title="Proyecto actual («esta carpeta»). Cámbialo en la barra lateral → Proyectos."
            onClick={() => update({ ...settings, sidebarOpen: true })}
          >
            <FolderIcon /> {settings.currentProject}
          </button>
        ) : null}
        {wakeStatus === "ready" ? (
          <span className={`wake-hint ${wakeIdle ? "" : "wake-hint--paused"}`} title="Detección local: el audio no sale de tu PC hasta que dices «Isabel»">
            <EarIcon /> Di «Isabel»
          </span>
        ) : wakeStatus === "loading" ? (
          <span className="wake-hint wake-hint--paused">Preparando «Isabel»…</span>
        ) : !settings.wakeWord ? (
          <span className="wake-hint wake-hint--muted">
            <MicOffIcon /> Micrófono silenciado
          </span>
        ) : null}
        <div className="topbar__actions">
          <button
            type="button"
            className={`icon-button ${settings.wakeWord ? "" : "icon-button--muted"}`}
            onClick={() => {
              if (settings.wakeWord) assistant.stopListeningAndTalking();
              update({ ...settings, wakeWord: !settings.wakeWord });
            }}
            aria-label={settings.wakeWord ? "Silenciar el micrófono: Isabel deja de escuchar" : "Activar el micrófono"}
            title={settings.wakeWord ? "Silenciar micrófono" : "Micrófono silenciado (pulsa para activar)"}
          >
            {settings.wakeWord ? <MicIcon /> : <MicOffIcon />}
          </button>
          <button
            type="button"
            className="icon-button"
            onClick={() => {
              if (settings.voiceReplies) assistant.silence();
              update({ ...settings, voiceReplies: !settings.voiceReplies });
            }}
            aria-label={settings.voiceReplies ? "Silenciar respuestas habladas" : "Activar respuestas habladas"}
            title={settings.voiceReplies ? "Voz activada" : "Voz desactivada"}
          >
            {settings.voiceReplies ? <SpeakerIcon /> : <MuteIcon />}
          </button>
          <button
            type="button"
            className={`icon-button ${settingsOpen ? "icon-button--active" : ""}`}
            onClick={() => setSettingsOpen((o) => !o)}
            aria-label="Personalizar la burbuja"
            title="Personalizar"
          >
            <TuneIcon />
          </button>
          {windowInfo?.customControls ? (
            <div className="window-controls">
              <button type="button" className="icon-button" onClick={() => void window.assistant?.windowControl("minimize")} aria-label="Minimizar" title="Minimizar">
                <MinimizeIcon />
              </button>
              <button type="button" className="icon-button" onClick={() => void window.assistant?.windowControl("maximize")} aria-label="Maximizar o restaurar" title="Maximizar">
                <MaximizeIcon />
              </button>
              <button type="button" className="icon-button icon-button--close" onClick={() => void window.assistant?.windowControl("close")} aria-label="Cerrar" title="Cerrar">
                <CloseIcon />
              </button>
            </div>
          ) : null}
        </div>
      </header>

      <Sidebar
        open={settings.sidebarOpen}
        vault={vault}
        onVaultChanged={loadVault}
        currentProject={settings.currentProject}
        onSelectProject={(project) => update({ ...settings, currentProject: project })}
        activity={assistant.activity}
        messages={assistant.messages}
        refreshKey={refreshKey}
        onNewConversation={assistant.newConversation}
        onLog={assistant.log}
        onNotice={(text) => assistant.setNotice(text)}
      />

      <VoiceGlow active={assistant.phase === "listening" || preview === "listening"} levels={assistant.levels} />

      <main className="stage">
        {loaded ? (
          <ParticleOrb settings={settings.orb} state={orbState} levels={assistant.levels} onHoverChange={setHovering} pulseKey={pulseKey} />
        ) : null}
        <div className="stage__bottom">
          <p className={`status ${status ? "status--visible" : ""}`} aria-live="polite">
            {status}
            {assistant.phase === "speaking" && settings.voiceReplies && !preview ? (
              <button type="button" className="status__stop" onClick={assistant.silence}>
                callar
              </button>
            ) : null}
          </p>
          {connection === "offline" ? (
            <p className="offline-hint">
              Inicia el backend con <code>docker compose up -d</code> en la carpeta del proyecto.
            </p>
          ) : (
            <AnswerView messages={assistant.messages} vaultName={vault?.name} />
          )}
          <Banner
            phase={assistant.phase}
            busy={assistant.busy}
            onSend={assistant.send}
            onToggleMic={assistant.toggleListening}
            locked={assistant.pending !== null}
          />
        </div>
        {notice ? (
          <div className="notice" role="status">
            {notice}
          </div>
        ) : null}
      </main>

      <SettingsPanel
        open={settingsOpen}
        settings={settings}
        activeMaterial={windowInfo?.material ?? null}
        wakeStatus={wakeStatus}
        preview={preview}
        onChange={update}
        onPreview={setPreview}
        onClose={() => {
          setSettingsOpen(false);
          setPreview(null);
        }}
      />

      {assistant.pending ? (
        <ApprovalCard
          pending={assistant.pending}
          onDecide={assistant.decide}
          voiceConfirm={wakeStatus === "ready" && listenMode === "confirm"}
        />
      ) : null}
    </div>
  );
}

function previewPhase(state: OrbState): keyof typeof STATUS_LABELS {
  return state === "alert" ? "awaiting" : state === "idle" ? "idle" : state;
}
