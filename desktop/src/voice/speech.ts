// Spoken replies with the operating system's voices (Web Speech API; local, no network
// on Windows). Each spoken word sends a pulse to the orb so it "talks".

export function spanishVoices(): SpeechSynthesisVoice[] {
  if (!("speechSynthesis" in window)) return [];
  return window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("es"));
}

/** Voices load asynchronously in Chromium; resolve once they are available. */
export function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (!("speechSynthesis" in window)) return Promise.resolve([]);
  const now = window.speechSynthesis.getVoices();
  if (now.length > 0) return Promise.resolve(spanishVoices());
  return new Promise((resolve) => {
    const done = () => resolve(spanishVoices());
    window.speechSynthesis.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, 1500);
  });
}

/** Text as it should be read aloud: no citations, markdown or code. */
export function speakableText(answer: string): string {
  return answer
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\[\d+\]/g, "")
    .replace(/[*_#`>|]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 1200);
}

// The natural-voice clip currently playing (so "callar" and a new message can stop it).
let current: { source: AudioBufferSourceNode; context: AudioContext; done: () => void } | null = null;

export function stopSpeaking() {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  if (current) {
    const playing = current;
    current = null;
    try {
      playing.source.stop();
    } catch {
      // already stopped
    }
    playing.done();
  }
}

/** Play a natural-voice WAV; the orb follows the real loudness of the voice.
 *  Resolves when the clip ends or is stopped. */
export async function playSpeech(wav: ArrayBuffer, onLevel: (level: number) => void): Promise<void> {
  stopSpeaking();
  const context = new AudioContext();
  let buffer: AudioBuffer;
  try {
    buffer = await context.decodeAudioData(wav);
  } catch (error) {
    void context.close(); // never leak audio contexts (Chromium limits how many exist)
    throw error;
  }
  const source = context.createBufferSource();
  source.buffer = buffer;
  const analyser = context.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);
  analyser.connect(context.destination);
  const samples = new Float32Array(analyser.fftSize);

  return new Promise((resolve) => {
    let frame = 0;
    const meter = () => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
      onLevel(Math.min(1, Math.sqrt(sum / samples.length) * 5));
      frame = requestAnimationFrame(meter);
    };
    const done = () => {
      cancelAnimationFrame(frame);
      onLevel(0);
      void context.close();
      if (current?.source === source) current = null;
      resolve();
    };
    current = { source, context, done };
    source.onended = () => current?.source === source && done();
    source.start();
    meter();
  });
}

interface SpeakOptions {
  voiceName: string | null;
  onPulse: (strength: number) => void;
}

/** Speak `text`; resolves when it finishes or is interrupted. */
export function speak(text: string, { voiceName, onPulse }: SpeakOptions): Promise<void> {
  const clean = speakableText(text);
  if (!clean || !("speechSynthesis" in window)) return Promise.resolve();
  stopSpeaking();
  return new Promise((resolve) => {
    const utterance = new SpeechSynthesisUtterance(clean);
    const voices = spanishVoices();
    const voice = voices.find((v) => v.name === voiceName) ?? voices[0];
    if (voice) utterance.voice = voice;
    utterance.lang = voice?.lang ?? "es-ES";
    utterance.rate = 1.02;
    // Word boundaries drive the orb; a gentle timer keeps it alive if a voice has none.
    let lastBoundary = performance.now();
    utterance.onboundary = (event) => {
      lastBoundary = performance.now();
      onPulse(0.55 + Math.min(event.charLength ?? 4, 10) * 0.045);
    };
    const keepAlive = window.setInterval(() => {
      if (performance.now() - lastBoundary > 280) onPulse(0.35 + Math.random() * 0.3);
    }, 240);
    const finish = () => {
      window.clearInterval(keepAlive);
      onPulse(0);
      resolve();
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  });
}
