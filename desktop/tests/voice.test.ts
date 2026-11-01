// Voice logic: who is being called, approvals by voice, and how answers are split for speech.
import { describe, expect, it, vi } from "vitest";

vi.mock("vosk-browser", () => ({ createModel: vi.fn() })); // the WebAssembly engine is not needed here

const { decisionFromWords, makeResampler, requestAfterName, stripWakeWord } = await import("../src/voice/wakeword");
const { splitForSpeech, speakableText } = await import("../src/voice/speech");

describe("requestAfterName", () => {
  it.each([
    ["Isabel, pon música", "pon música"],
    ["Bueno, ya me voy. Isabel, ¿qué hora es?", "¿qué hora es?"],
    ["Israel y pon algo de Maluma", "pon algo de Maluma"],
    ["Isabel.", ""],
  ])("%s → %s", (text, request) => {
    expect(requestAfterName(text)).toBe(request);
  });

  it.each(["Oye, ¿y si vamos al cine mañana?", "La isabelina era otra época", "Le dije a Isabel que viniera", "la casa de Isabel"])(
    "ignores %s (not calling her)",
    (text) => {
      expect(requestAfterName(text)).toBeNull();
    },
  );

  it("strips the name at the start", () => {
    expect(stripWakeWord("Isabel, apaga la música")).toBe("apaga la música");
  });
});

describe("decisionFromWords", () => {
  it("approves only a clear, confident «apruebo»", () => {
    expect(decisionFromWords([{ word: "apruebo", conf: 0.95 }])).toBe("approve");
    expect(decisionFromWords([{ word: "apruebo", conf: 0.6 }])).toBeNull();
    expect(decisionFromWords([{ word: "sí", conf: 1 }])).toBeNull();
    expect(decisionFromWords([{ word: "apruebo", conf: 1 }, { word: "sí", conf: 1 }])).toBeNull();
  });

  it("rejects on any «no»-like word", () => {
    expect(decisionFromWords([{ word: "no", conf: 0.5 }])).toBe("reject");
    expect(decisionFromWords([{ word: "apruebo", conf: 1 }, { word: "cancela", conf: 0.7 }])).toBe("reject");
  });
});

describe("splitForSpeech", () => {
  it("keeps a short answer in one piece", () => {
    expect(splitForSpeech("Son las siete y media.")).toEqual(["Son las siete y media."]);
  });

  it("starts with a short piece and never cuts a sentence", () => {
    const answer = "Listo, te pongo música. ".repeat(3) + "Además, mañana tienes dos recordatorios pendientes y una tarea en Obsidian. ".repeat(6);
    const pieces = splitForSpeech(answer.trim());
    expect(pieces.length).toBeGreaterThan(1);
    expect(pieces[0].length).toBeLessThanOrEqual(140);
    expect(pieces.join(" ")).toBe(answer.trim());
    for (const piece of pieces) expect(piece).toMatch(/[.!?…]$/);
  });

  it("speakableText drops citations and Markdown", () => {
    expect(speakableText("**Hola** [1], esto es `código`.")).toBe("Hola , esto es código.");
  });
});

describe("makeResampler", () => {
  it("turns 48 kHz float audio into 16 kHz int16, chunk after chunk", () => {
    const resample = makeResampler(48000);
    const second = new Float32Array(48000).fill(0.5);
    const out = [...resample(second.subarray(0, 4096)), ...resample(second.subarray(4096))];
    expect(out.length).toBe(16000);
    expect(out.every((s) => s === Math.round(0.5 * 32767))).toBe(true);
  });

  it("clips out-of-range samples", () => {
    expect([...makeResampler(16000)(new Float32Array([2, -2]))]).toEqual([32767, -32767]);
  });
});
