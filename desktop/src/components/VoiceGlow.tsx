import { useEffect, useRef } from "react";
import type { AudioLevels } from "../orb/OrbEngine";

interface Props {
  active: boolean;
  levels: AudioLevels;
}

/** Soft light along the window edges and under the mic while voice is being recorded.
 *  It breathes with the microphone level; the level is written to a CSS variable every
 *  frame (no React re-render). */
export function VoiceGlow({ active, levels }: Props) {
  const element = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!active) return;
    let frame = 0;
    let smooth = 0;
    const step = () => {
      smooth += (levels.mic - smooth) * 0.18;
      element.current?.style.setProperty("--mic", smooth.toFixed(3));
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(frame);
      element.current?.style.setProperty("--mic", "0");
    };
  }, [active, levels]);

  return <div ref={element} className={`voice-glow ${active ? "voice-glow--on" : ""}`} aria-hidden="true" />;
}
