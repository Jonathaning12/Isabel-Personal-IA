// Local voice listening with Vosk (speech recognition in WebAssembly), in two modes:
// - "wake":    waits for the word "Isabel" to start a voice command;
// - "confirm": while an approval is pending, waits for "sí / apruebo / confirmo" or
//              "no / rechazar / cancelar".
// Each mode has its own tiny grammar (plus "[unk]" for everything else), which keeps the
// recognizer light and avoids false triggers. No audio leaves the machine here: only after
// the wake word does the app record the command and send it for transcription.
//
// "Isabel" only counts on a complete utterance recognized with MIN_WAKE_CONFIDENCE: with a
// two-word grammar, early partial guesses turned ordinary conversation into "isabel" and
// started recordings nobody asked for. Because the decision comes at the end of the
// utterance, the last PREROLL_SECONDS of audio are kept, so a command said in the same
// breath ("Isabel, ¿qué hora es?") is not cut off. The app then checks that the
// transcription really contains the name (requestAfterName) before doing anything.

// Types only: the engine itself (~6 MB of WebAssembly) is loaded on first use, so the app
// opens fast and never loads it while the microphone is muted.
import type { KaldiRecognizer, Model } from "vosk-browser";

const WAKE_WORD = "isabel";
// Approving must be deliberate: only long, distinctive words, recognized with high
// confidence. Short words ("sí", "dale") are easily confused with any sound by a small
// grammar; a test approved an action from a misheard "no". "sí" stays in the grammar only
// to absorb that sound, and never approves on its own. Rejecting is always safe, so any
// "no"-like word rejects.
const YES = ["apruebo", "confirmo"];
const NO = ["no", "rechazar", "rechazo", "cancelar", "cancela"];
const FILLER = ["sí"];
const MIN_YES_CONFIDENCE = 0.9;
const MIN_WAKE_CONFIDENCE = 0.8;
const PREROLL_SECONDS = 6;
const COOLDOWN_MS = 2500;
const RESUME_GRACE_MS = 1200; // ignore results right after a mode starts

export type WakeStatus = "loading" | "ready" | "unavailable" | "error";
export type ListenMode = "wake" | "confirm" | "off";

export interface Preroll {
  samples: Float32Array;
  rate: number;
}

export interface WakeListener {
  /** What to listen for now (e.g. "wake" only while idle, "confirm" during an approval). */
  setMode(mode: ListenMode): void;
  /** The most recent audio, oldest first. */
  preroll(): Preroll;
  stop(): void;
}

interface Options {
  modelUrl: string;
  onWake: () => void;
  onConfirm: (decision: "approve" | "reject") => void;
  onStatus: (status: WakeStatus) => void;
}

let modelPromise: Promise<Model> | null = null; // loaded once per app run

function loadModel(url: string): Promise<Model> {
  modelPromise ??= import("vosk-browser")
    .then(({ createModel }) => createModel(url))
    .catch((error) => {
      modelPromise = null; // a failed load can be retried (toggle the setting off and on)
      throw error;
    });
  return modelPromise;
}

export interface HeardWord {
  word: string;
  conf: number;
}

/** "no, cancela" → reject; "apruebo" (confident) → approve; anything else → null. */
export function decisionFromWords(heard: HeardWord[]): "approve" | "reject" | null {
  const words = heard.map((w) => ({ ...w, word: w.word.toLowerCase() })).filter((w) => w.word !== "[unk]");
  if (words.some((w) => NO.includes(w.word))) return "reject";
  // Approve only if the whole utterance is a clear "apruebo"/"confirmo" (nothing else).
  if (words.length === 1 && YES.includes(words[0].word) && words[0].conf >= MIN_YES_CONFIDENCE) return "approve";
  return null;
}

export async function startWakeListener({ modelUrl, onWake, onConfirm, onStatus }: Options): Promise<WakeListener> {
  onStatus("loading");
  const model = await loadModel(modelUrl);
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  let context: AudioContext | null = null;
  try {
    context = new AudioContext();
    return build(model, stream, context, { onWake, onConfirm, onStatus });
  } catch (error) {
    // Never leave the microphone open if anything after getUserMedia fails.
    stream.getTracks().forEach((track) => track.stop());
    void context?.close();
    throw error;
  }
}

function build(
  model: Model,
  stream: MediaStream,
  context: AudioContext,
  { onWake, onConfirm, onStatus }: Omit<Options, "modelUrl">,
): WakeListener {
  const rate = context.sampleRate;
  const wake = new model.KaldiRecognizer(rate, JSON.stringify([WAKE_WORD, "[unk]"]));
  wake.setWords(true); // per-word confidence, required to wake
  const confirm = new model.KaldiRecognizer(rate, JSON.stringify([...YES, ...NO, ...FILLER, "[unk]"]));
  confirm.setWords(true); // per-word confidence, required to approve
  const source = context.createMediaStreamSource(stream);
  const processor = context.createScriptProcessor(4096, 1, 1);

  const ring = new Float32Array(Math.ceil(rate * PREROLL_SECONDS));
  let ringPos = 0;
  let mode: ListenMode = "off";
  let lastWake = 0;
  let ignoreUntil = 0;

  const recognizerFor = (m: ListenMode): KaldiRecognizer | null => (m === "wake" ? wake : m === "confirm" ? confirm : null);

  const setMode = (next: ListenMode) => {
    if (next === mode) return;
    // Close the utterance in progress: otherwise its partial result is reported again as
    // soon as listening resumes (she would wake herself up in a loop).
    recognizerFor(mode)?.retrieveFinalResult();
    mode = next;
    ignoreUntil = performance.now() + RESUME_GRACE_MS;
  };

  wake.on("result", (m) => {
    if (mode !== "wake") return;
    const words = (m as { result?: { result?: HeardWord[] } }).result?.result ?? [];
    const name = words.find((w) => w.word === WAKE_WORD);
    if (!name) return;
    console.info(`wake word candidate: ${words.map((w) => `${w.word}(${w.conf.toFixed(2)})`).join(" ")}`);
    const now = performance.now();
    if (name.conf < MIN_WAKE_CONFIDENCE || now < ignoreUntil || now - lastWake < COOLDOWN_MS) return;
    lastWake = now;
    setMode("off"); // the app sets the next mode once it is idle again
    onWake();
  });

  // Approvals only count on a complete utterance ("result"), never on a partial guess.
  confirm.on("result", (m) => {
    if (mode !== "confirm" || performance.now() < ignoreUntil) return;
    const result = (m as { result?: { text?: string; result?: HeardWord[] } }).result;
    const words = result?.result ?? [];
    console.info(`voice approval heard: ${words.map((w) => `${w.word}(${w.conf.toFixed(2)})`).join(" ") || result?.text || "-"}`);
    const decision = decisionFromWords(words);
    if (!decision) return;
    setMode("off");
    onConfirm(decision);
  });

  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0);
    for (let i = 0; i < input.length; i++) {
      ring[ringPos] = input[i];
      ringPos = (ringPos + 1) % ring.length;
    }
    recognizerFor(mode)?.acceptWaveformFloat(new Float32Array(input), rate);
  };
  source.connect(processor);
  processor.connect(context.destination);
  onStatus("ready");

  return {
    setMode,
    preroll() {
      const out = new Float32Array(ring.length);
      out.set(ring.subarray(ringPos));
      out.set(ring.subarray(0, ringPos), ring.length - ringPos);
      return { samples: out, rate };
    },
    stop() {
      processor.disconnect();
      source.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      wake.remove();
      confirm.remove();
      void context.close();
    },
  };
}

// Transcription often mishears the name ("Israel y nosotros…" for "Isabel, nosotros…").
const NAME = "(isabel+a?|isab[eé]l|israel|isable|y\\s+sabel|y\\s+isabel)";

/** What was said after the name: "…bueno. Isabel, pon música" → "pon música".
 * "" if only the name was said; null if the name is not there at all (a false wake-up:
 * the recording is then dropped and nothing is sent to the agent). */
export function requestAfterName(text: string): string | null {
  const match = new RegExp(`(^|[^a-záéíóúñ])${NAME}(?![a-záéíóúñ])`, "i").exec(text);
  if (!match) return null;
  // "le dije a Isabel…", "la casa de Isabel": talking about her, not to her.
  if (/(^|\s)(a|de|con|para|la|por)\s*$/i.test(text.slice(0, match.index + match[1].length))) return null;
  return text
    .slice(match.index + match[0].length)
    .replace(/^(\s+y\b)?[\s,.:;!?-]*/i, "")
    .trim();
}

/** "Isabel, ¿qué hora es?" → "¿qué hora es?" (the name is how she was called, not the request). */
export function stripWakeWord(text: string): string {
  const name = NAME;
  const pattern = new RegExp(`^\\s*[¡¿]?\\s*(oye\\s+|hola\\s+)?${name}\\b(\\s+y\\b)?[\\s,.:;!¡?¿-]*`, "i");
  return text.replace(pattern, "").trim() || text.trim();
}
