import { useEffect, useRef } from "react";
import { type AudioLevels, OrbEngine, type OrbState } from "./OrbEngine";
import type { OrbSettings } from "./settings";

interface Props {
  settings: OrbSettings;
  state: OrbState;
  levels: AudioLevels;
  onHoverChange?: (hovering: boolean) => void;
  /** Incremented by the parent to trigger a burst (e.g. when an answer arrives). */
  pulseKey?: number;
}

/** React wrapper around OrbEngine: creates it once, then forwards prop changes. */
export function ParticleOrb({ settings, state, levels, onHoverChange, pulseKey = 0 }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const engine = useRef<OrbEngine | null>(null);
  const hoverCallback = useRef(onHoverChange);
  hoverCallback.current = onHoverChange;

  useEffect(() => {
    if (!container.current) return;
    const orb = new OrbEngine(container.current, settings, levels, (h) => hoverCallback.current?.(h));
    engine.current = orb;
    return () => {
      orb.dispose();
      engine.current = null;
    };
    // The engine is created once; later changes go through the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => engine.current?.setSettings(settings), [settings]);
  useEffect(() => engine.current?.setState(state), [state]);
  useEffect(() => {
    if (pulseKey > 0) engine.current?.pulse();
  }, [pulseKey]);

  return <div ref={container} className="orb-canvas" aria-hidden="true" />;
}
