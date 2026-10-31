// The app's conversation logic: sends messages, handles approvals, drives the orb state,
// records activity and speaks answers. Components only render what this hook returns.

import { useCallback, useEffect, useRef, useState } from "react";
import { type Action, ApiError, type ChatResponse, type Citation, type PendingAction, api } from "./api";
import { toolLabel, DECISION_LABELS } from "./lib/labels";
import { loadThreadId, saveThreadId } from "./lib/storage";
import type { AudioLevels, OrbState } from "./orb/OrbEngine";
import { type Recording, startRecording } from "./voice/recorder";
import { playSpeech, speak, speakableText, stopSpeaking } from "./voice/speech";
import { type Preroll, requestAfterName, stripWakeWord } from "./voice/wakeword";

export type Phase = "idle" | "gathering" | "thinking" | "speaking" | "listening" | "transcribing" | "awaiting" | "error";

export interface Message {
  id: number;
  role: "user" | "assistant" | "system";
  text: string;
  citations?: Citation[];
  at: Date;
}

export interface ActivityItem {
  id: number;
  at: Date;
  kind: "message" | "tool" | "approval" | "voice" | "docs" | "error";
  title: string;
  detail?: string;
  status?: "ok" | "warn" | "error";
}

const PHASE_TO_ORB: Record<Phase, OrbState> = {
  idle: "idle",
  gathering: "gathering",
  thinking: "thinking",
  speaking: "speaking",
  listening: "listening",
  transcribing: "thinking",
  awaiting: "alert",
  error: "error",
};

// Every turn starts by searching the notes (load_context), so the first moments are
// shown as "gathering" and the rest as "thinking". The API is not streamed yet, so this
// split is an approximation in time, not a live signal.
const GATHERING_MS = 1300;
const ERROR_MS = 1800;
const SILENT_SPEAKING_MS = 1600;
const WAKE_SILENCE_MS = 2200; // people pause after saying a name
// After she answers a voice request she keeps listening this long without her name
// (to continue the conversation or answer her question); then only "Isabel" wakes her.
const FOLLOW_UP_MS = 15000;
// The API tries the Gemini voice (two models, ~7 s each, skipped while out of quota), then
// the local Piper voice; only after that the Windows voice.
const NATURAL_VOICE_TIMEOUT_MS = 30000;

/** The API accepts computer-action results up to 8 000 characters of JSON. */
const MAX_RESULT_CHARS = 7000;

function fitResult(result: Record<string, unknown>): Record<string, unknown> {
  const json = JSON.stringify(result);
  if (json.length <= MAX_RESULT_CHARS) return result;
  return { status: result.status ?? "ok", truncated: true, data: json.slice(0, MAX_RESULT_CHARS - 200) };
}

/** Phases in which a request is in flight or an approval is open. */
const isBusy = (p: Phase) => p === "gathering" || p === "thinking" || p === "transcribing" || p === "awaiting";

interface Options {
  voiceReplies: boolean;
  voiceName: string | null;
  voiceEngine: "natural" | "system";
  naturalVoice: string;
  /** Project folder selected in the app: "esta carpeta" for git requests. */
  project: string | null;
  /** The name the user set in Settings (greetings, reminders). */
  userName: string;
  /** Hands-free listening is on (the mic is not muted): enables the follow-up window. */
  handsFree: boolean;
  onDataChanged: () => void;
}

/** Why the mic is recording: the mic button, the wake word, or the follow-up window. */
type ListenKind = "manual" | "wake" | "followup";

export function useAssistant({
  voiceReplies,
  voiceName,
  voiceEngine,
  naturalVoice,
  project,
  userName,
  handsFree,
  onDataChanged,
}: Options) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [messages, setMessages] = useState<Message[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(() => loadThreadId());
  const [askingAloud, setAskingAloud] = useState(false); // reading an approval request aloud
  const levels = useRef<AudioLevels>({ speech: 0, mic: 0 }).current;
  const counter = useRef(0);
  const turnActions = useRef(0); // actions of the current turn already logged
  const recording = useRef<Recording | null>(null);
  const startingMic = useRef(false);
  const listenKind = useRef<ListenKind>("manual");
  const lastTurnByVoice = useRef(false); // the current conversation turn was spoken
  const followUp = useRef<() => void>(() => {}); // opens the follow-up window (set below)
  // Incremented by "new conversation": replies that belong to an older one are dropped.
  const generation = useRef(0);
  const phaseTimer = useRef<number | undefined>(undefined);
  const options = useRef({ voiceReplies, voiceName, voiceEngine, naturalVoice, project, userName, handsFree, onDataChanged });
  options.current = { voiceReplies, voiceName, voiceEngine, naturalVoice, project, userName, handsFree, onDataChanged };
  // Latest values for callbacks that outlive a render (e.g. the recorder's auto-stop).
  const live = useRef({ phase, threadId, pending });
  live.current = { phase, threadId, pending };

  const nextId = () => ++counter.current;
  const log = useCallback((item: Omit<ActivityItem, "id" | "at">) => {
    setActivity((all) => [{ ...item, id: ++counter.current, at: new Date() }, ...all].slice(0, 200));
  }, []);

  useEffect(() => saveThreadId(threadId), [threadId]);
  useEffect(() => () => window.clearTimeout(phaseTimer.current), []);

  const fail = useCallback(
    (error: unknown) => {
      const message = error instanceof ApiError ? error.message : "Error inesperado.";
      setNotice(message);
      log({ kind: "error", title: "Error", detail: message, status: "error" });
      setPhase("error");
      window.clearTimeout(phaseTimer.current);
      phaseTimer.current = window.setTimeout(() => setPhase((p) => (p === "error" ? "idle" : p)), ERROR_MS);
    },
    [log],
  );

  const logActions = useCallback(
    (actions: Action[]) => {
      for (const action of actions.slice(turnActions.current)) {
        const decided = action.decision ? DECISION_LABELS[action.decision] : undefined;
        const status = action.decision === "approve" || !action.decision ? "ok" : "warn";
        let detail = decided;
        if (action.tool === "search_knowledge") {
          const found = (action.result.results as unknown[] | undefined)?.length ?? 0;
          detail = `«${String(action.args.query ?? "")}» · ${found} resultado(s)`;
        } else if (action.tool === "run_code_in_sandbox" || action.tool === "run_skill") {
          const exit = action.result.exit_code;
          detail = [decided, exit !== undefined ? `código de salida ${String(exit)}` : null].filter(Boolean).join(" · ");
        }
        log({ kind: "tool", title: toolLabel(action.tool), detail, status });
      }
      turnActions.current = actions.length;
    },
    [log],
  );

  /** Read an answer aloud: Gemini voice, local Piper voice, or the system voice as a last resort. */
  const speakAnswer = useCallback(
    async (answer: string, turn: number, during: Phase = "speaking") => {
      const { voiceEngine: engine, naturalVoice: voice, voiceName: systemVoice } = options.current;
      if (engine === "natural") {
        try {
          // The TTS service can be slow at peak times: never leave her silent for long.
          const wav = await Promise.race([
            api.speech(speakableText(answer), voice),
            new Promise<never>((_, reject) => window.setTimeout(() => reject(new Error("slow")), NATURAL_VOICE_TIMEOUT_MS)),
          ]);
          // Skip if the user moved on while the voice was being generated.
          if (turn !== generation.current || live.current.phase !== during) return;
          await playSpeech(wav, (level) => {
            levels.speech = level;
          });
          return;
        } catch {
          // Natural voice unavailable (provider busy, Nebius, offline): use the system voice.
        }
      }
      await speak(answer, {
        voiceName: systemVoice,
        onPulse: (strength) => {
          levels.speech = Math.max(levels.speech, strength);
        },
      });
    },
    [levels],
  );

  const deliver = useCallback(
    async (response: ChatResponse, turn: number) => {
      if (turn !== generation.current) return; // the user started a new conversation meanwhile
      console.info(`chat: ${response.status}${response.pending ? ` (${response.pending.tool})` : ""}`);
      window.clearTimeout(phaseTimer.current);
      setThreadId(response.thread_id);
      logActions(response.actions);
      if (response.status === "client_action" && response.pending) {
        // The agent asks this app to act on the computer (music, Spotify): run it here and
        // hand the result back so she can answer.
        const action = response.pending;
        const bridge = window.assistant;
        const result = bridge
          ? await bridge.runAction(action.tool, action.args, response.thread_id, action.tool_call_id)
          : { status: "error", error: "Only the desktop app can do this." };
        // Always answer the API (even after "new conversation" or an error): otherwise the
        // thread stays blocked on this action.
        let next: ChatResponse;
        try {
          next = await api.clientResult(response.thread_id, action.tool_call_id, fitResult(result));
        } catch {
          next = await api.clientResult(response.thread_id, action.tool_call_id, {
            status: "error",
            error: "The result could not be delivered.",
          });
        }
        if (turn !== generation.current) return;
        await deliver(next, turn);
        return;
      }
      if (response.status === "confirm_required" && response.pending) {
        setPending(response.pending);
        setPhase("awaiting");
        log({ kind: "approval", title: "Aprobación pendiente", detail: toolLabel(response.pending.tool), status: "warn" });
        if (options.current.voiceReplies) {
          // Say what needs approval; the voice "sí / no" listener starts when she stops.
          setAskingAloud(true);
          await speakAnswer(
            `Necesito tu aprobación para: ${toolLabel(response.pending.tool)}. Di «apruebo» para hacerlo, o «no» para cancelar.`,
            turn,
            "awaiting",
          );
          setAskingAloud(false);
        }
        return;
      }
      setPending(null);
      const answer = response.answer ?? "";
      setMessages((all) => [...all, { id: nextId(), role: "assistant", text: answer, citations: response.citations, at: new Date() }]);
      if (response.actions.some((a) => a.decision === "approve")) options.current.onDataChanged();
      setPhase("speaking");
      if (options.current.voiceReplies) {
        await speakAnswer(answer, turn);
        setPhase((p) => (p === "speaking" ? "idle" : p));
        if (turn === generation.current) followUp.current();
      } else {
        phaseTimer.current = window.setTimeout(() => {
          setPhase((p) => (p === "speaking" ? "idle" : p));
          if (turn === generation.current) followUp.current();
        }, SILENT_SPEAKING_MS);
      }
    },
    [levels, log, logActions, speakAnswer],
  );

  const busy = isBusy(phase);

  const send = useCallback(
    /** `automatic`: sent by the app on its own (the morning greeting), shown as a note. */
    async (text: string, fromVoice = false, automatic = false) => {
      const message = text.trim();
      const current = live.current.phase;
      // A voice message arrives while the phase is still "transcribing".
      const blocked = isBusy(current) && !(fromVoice && current === "transcribing");
      if (!message || blocked) return;
      if (!fromVoice && recording.current) {
        // Typing while the mic is open: the typed message wins, the recording is dropped.
        recording.current.cancel();
        recording.current = null;
      }
      const thread = live.current.threadId;
      const turn = generation.current;
      stopSpeaking();
      setNotice(null);
      turnActions.current = 0;
      const shown = automatic ? { role: "system" as const, text: "☀️ Buenos días automáticos" } : { role: "user" as const, text: message };
      setMessages((all) => [...all, { id: nextId(), ...shown, at: new Date() }]);
      log({ kind: "message", title: automatic ? "Buenos días automáticos" : "Mensaje enviado", detail: shown.text.slice(0, 120) });
      const extra = { userName: options.current.userName, automatic };
      lastTurnByVoice.current = fromVoice || automatic;
      setPhase("gathering");
      window.clearTimeout(phaseTimer.current);
      phaseTimer.current = window.setTimeout(() => setPhase((p) => (p === "gathering" ? "thinking" : p)), GATHERING_MS);
      try {
        await deliver(await api.chat(message, thread, options.current.project, extra), turn);
      } catch (error) {
        if (turn !== generation.current) return;
        if (error instanceof ApiError && error.status === 409 && thread) {
          // An approval from an earlier session is still waiting on that thread:
          // start a new conversation and send the message there.
          setThreadId(null);
          log({ kind: "message", title: "Conversación nueva", detail: "La anterior tenía una acción pendiente", status: "warn" });
          try {
            await deliver(await api.chat(message, null, options.current.project, extra), turn);
          } catch (retryError) {
            if (turn === generation.current) fail(retryError);
          }
          return;
        }
        fail(error);
      }
    },
    [deliver, fail, log],
  );

  const decide = useCallback(
    async (decision: "approve" | "reject") => {
      const action = live.current.pending;
      const thread = live.current.threadId;
      if (!action || !thread) return;
      const turn = generation.current;
      log({
        kind: "approval",
        title: decision === "approve" ? "Aprobaste la acción" : "Rechazaste la acción",
        detail: toolLabel(action.tool),
        status: decision === "approve" ? "ok" : "warn",
      });
      stopSpeaking(); // she may still be reading the request aloud
      setAskingAloud(false);
      setPending(null);
      setPhase("thinking");
      try {
        await deliver(await api.confirm(thread, decision), turn);
      } catch (error) {
        if (turn !== generation.current) return;
        // The action is still waiting on the server unless it says there is none (409):
        // show the card again so the user can retry.
        if (!(error instanceof ApiError && error.status === 409)) {
          setPending(action);
          setPhase("awaiting");
          setNotice(error instanceof ApiError ? `${error.message} Puedes intentarlo otra vez.` : "Error inesperado.");
          return;
        }
        fail(error);
      }
    },
    [deliver, fail, log],
  );

  const stopListening = useCallback(async () => {
    const active = recording.current;
    if (!active) return;
    recording.current = null;
    const turn = generation.current;
    const kind = listenKind.current;
    const wav = await active.stop();
    if (turn !== generation.current) return;
    if (!wav) {
      setPhase((p) => (p === "listening" ? "idle" : p));
      // The follow-up window just closes when nobody speaks; only the mic button complains.
      if (kind === "manual") setNotice("No escuché nada. Prueba de nuevo, un poco más cerca del micrófono.");
      return;
    }
    setPhase("transcribing");
    try {
      const text = await api.transcribe(wav);
      if (turn !== generation.current) return;
      if (!text) {
        setPhase("idle");
        if (kind === "manual") setNotice("No entendí el audio. ¿Lo intentas otra vez?");
        return;
      }
      let request = stripWakeWord(text);
      if (kind === "wake") {
        // Woken by the name: only what follows the name is the request ("…bueno. Isabel,
        // pon música" → "pon música"). Without the name it was a false wake-up: drop it.
        const afterName = requestAfterName(text);
        if (afterName === null) {
          console.info("voice: no name in the transcription, ignored");
          log({ kind: "voice", title: "Ignorado: no dijiste «Isabel»", status: "warn" });
          setPhase("idle");
          return;
        }
        if (!afterName) {
          // Just "Isabel": she listens for the request, no name needed.
          setPhase("idle");
          lastTurnByVoice.current = true;
          followUp.current();
          return;
        }
        request = afterName;
      }
      console.info(`voice: transcribed ${request.length} chars`);
      log({ kind: "voice", title: "Voz transcrita", detail: request.slice(0, 120) });
      await send(request, true);
    } catch (error) {
      if (turn === generation.current) fail(error);
    }
  }, [fail, log, send]);

  const startListening = useCallback(
    async (preroll?: Preroll, kind: ListenKind = preroll ? "wake" : "manual") => {
      if (recording.current || startingMic.current || isBusy(live.current.phase)) return;
      startingMic.current = true;
      listenKind.current = kind;
      if (kind !== "followup") stopSpeaking();
      setNotice(null);
      try {
        const started = await startRecording({
          onLevel: (level) => {
            levels.mic = level;
          },
          // Only the recording that is still active may stop itself.
          onAutoStop: () => {
            if (recording.current === started) void stopListening();
          },
          preroll,
          silenceMs: preroll ? WAKE_SILENCE_MS : undefined,
          noSpeechMs: kind === "followup" ? FOLLOW_UP_MS : undefined,
        });
        if (isBusy(live.current.phase)) {
          started.cancel(); // something else started while the mic was opening
          return;
        }
        recording.current = started;
        setPhase("listening");
      } catch {
        fail(new ApiError(0, "No tengo acceso al micrófono. Revisa los permisos de Windows."));
      } finally {
        startingMic.current = false;
      }
    },
    [fail, levels, stopListening],
  );

  // The follow-up window: only after a spoken turn, with hands-free listening on and
  // nothing else going on. If nobody speaks within FOLLOW_UP_MS it closes by itself.
  followUp.current = () => {
    if (!options.current.handsFree || !lastTurnByVoice.current || live.current.pending) return;
    log({ kind: "voice", title: "Te escucho 15 s sin decir «Isabel»" });
    void startListening(undefined, "followup");
  };

  const toggleListening = useCallback(async () => {
    if (recording.current) await stopListening();
    else await startListening();
  }, [startListening, stopListening]);

  /** The wake word was heard: start recording, keeping what was said with the name. */
  const wake = useCallback(
    (preroll: Preroll) => {
      const current = live.current.phase;
      if (recording.current || isBusy(current)) return;
      log({ kind: "voice", title: "Te escuché: «Isabel»" });
      void startListening(preroll);
    },
    [log, startListening],
  );

  const newConversation = useCallback(() => {
    generation.current += 1;
    recording.current?.cancel();
    recording.current = null;
    stopSpeaking();
    window.clearTimeout(phaseTimer.current);
    setThreadId(null);
    setMessages([]);
    setPending(null);
    setPhase("idle");
    setNotice(null);
    log({ kind: "message", title: "Nueva conversación" });
  }, [log]);

  /** Say something on her own (e.g. a reminder that is due), when she is not busy. */
  const announce = useCallback(
    async (text: string) => {
      if (isBusy(live.current.phase) || recording.current) return;
      setPhase("speaking");
      if (options.current.voiceReplies) await speakAnswer(text, generation.current);
      else await new Promise((resolve) => window.setTimeout(resolve, SILENT_SPEAKING_MS));
      setPhase((p) => (p === "speaking" ? "idle" : p));
    },
    [speakAnswer],
  );

  /** The mute button: stop recording (discarding it) and stop talking, right now. */
  const stopListeningAndTalking = useCallback(() => {
    recording.current?.cancel();
    recording.current = null;
    stopSpeaking();
    setPhase((p) => (p === "listening" || p === "speaking" ? "idle" : p));
  }, []);

  const silence = useCallback(() => {
    stopSpeaking();
    setPhase((p) => (p === "speaking" ? "idle" : p));
  }, []);

  return {
    phase,
    orbState: PHASE_TO_ORB[phase],
    levels,
    busy,
    messages,
    activity,
    pending,
    askingAloud,
    notice,
    setNotice,
    log,
    send,
    decide,
    toggleListening,
    wake,
    newConversation,
    silence,
    announce,
    stopListeningAndTalking,
  };
}
