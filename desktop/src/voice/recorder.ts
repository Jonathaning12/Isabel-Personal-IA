// Microphone capture: records mono audio, reports its level (for the orb) and encodes
// a 16 kHz 16-bit WAV, the format /transcribe expects. Stops by itself after the user
// stops talking, or at MAX_SECONDS.

const TARGET_RATE = 16000;
const MAX_SECONDS = 60;
const SPEECH_LEVEL = 0.06; // above this RMS level we consider the user is talking
const SILENCE_MS = 1600; // stop after this much silence once speech started
const NO_SPEECH_MS = 8000; // give up if nobody talks

export interface Recording {
  /** Stop now and return the WAV (or null if nothing was said). */
  stop(): Promise<ArrayBuffer | null>;
  cancel(): void;
}

interface Options {
  onLevel: (level: number) => void;
  /** Called when the recorder stops by itself (silence or time limit). */
  onAutoStop: () => void;
  /** Audio captured just before recording started (the wake word and what followed it). */
  preroll?: { samples: Float32Array; rate: number };
  /** Silence that ends the recording; longer after the wake word, people pause after a name. */
  silenceMs?: number;
  /** Give up after this long if nobody talks (the follow-up window waits longer). */
  noSpeechMs?: number;
}

export async function startRecording({
  onLevel,
  onAutoStop,
  preroll,
  silenceMs = SILENCE_MS,
  noSpeechMs = NO_SPEECH_MS,
}: Options): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  const context = new AudioContext();
  const source = context.createMediaStreamSource(stream);
  // ScriptProcessor is deprecated but universally available and enough for short clips.
  const processor = context.createScriptProcessor(4096, 1, 1);
  const chunks: Float32Array[] = [];
  const started = performance.now();
  // With a preroll the user has already spoken (at least the wake word).
  let heardSpeech = preroll !== undefined;
  let lastSpeech = started;
  let finished = false;

  processor.onaudioprocess = (event) => {
    if (finished) return;
    const input = event.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(input));
    let sum = 0;
    for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
    const rms = Math.sqrt(sum / input.length);
    onLevel(Math.min(1, rms * 6));
    const now = performance.now();
    if (rms > SPEECH_LEVEL) {
      heardSpeech = true;
      lastSpeech = now;
    }
    const silentTooLong = heardSpeech && now - lastSpeech > silenceMs;
    const nobodyTalked = !heardSpeech && now - started > noSpeechMs;
    if (silentTooLong || nobodyTalked || now - started > MAX_SECONDS * 1000) onAutoStop();
  };
  source.connect(processor);
  processor.connect(context.destination);

  const release = () => {
    finished = true;
    processor.disconnect();
    source.disconnect();
    stream.getTracks().forEach((track) => track.stop());
    void context.close();
    onLevel(0);
  };

  return {
    async stop() {
      if (finished) return null;
      const rate = context.sampleRate;
      release();
      if (!heardSpeech) return null;
      const recorded = downsample(merge(chunks), rate, TARGET_RATE);
      const before = preroll ? downsample(preroll.samples, preroll.rate, TARGET_RATE) : new Float32Array(0);
      return encodeWav(merge([before, recorded]), TARGET_RATE);
    },
    cancel: release,
  };
}

function merge(chunks: Float32Array[]): Float32Array {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

/** Average-based downsampling (good enough for speech). */
function downsample(samples: Float32Array, from: number, to: number): Float32Array {
  if (to >= from) return samples;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), samples.length);
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    out[i] = sum / Math.max(end - start, 1);
  }
  return out;
}

function encodeWav(samples: Float32Array, rate: number): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true); // PCM header size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true); // bytes per second
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}
