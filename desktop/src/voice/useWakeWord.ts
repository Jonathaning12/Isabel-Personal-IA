// Runs the local voice listener while it is enabled. The app decides the mode:
// "wake" while idle, "confirm" while an approval is pending, "off" otherwise (never while
// she records, thinks or speaks: her own voice saying "Isabel" or "sí" must not count).

import { useEffect, useRef, useState } from "react";
import { type ListenMode, type Preroll, startWakeListener, type WakeListener, type WakeStatus } from "./wakeword";

export type WakeState = WakeStatus | "off";

interface Handlers {
  onWake: (preroll: Preroll) => void;
  onConfirm: (decision: "approve" | "reject") => void;
}

export function useWakeWord(enabled: boolean, mode: ListenMode, handlers: Handlers): WakeState {
  const [status, setStatus] = useState<WakeState>("off");
  const listener = useRef<WakeListener | null>(null);
  const callbacks = useRef(handlers);
  callbacks.current = handlers;
  const modeRef = useRef(mode);
  modeRef.current = mode;

  useEffect(() => {
    const bridge = window.assistant;
    if (!enabled || !bridge) {
      setStatus("off");
      return;
    }
    let cancelled = false;
    void (async () => {
      const model = await bridge.wakeModel();
      if (cancelled) return;
      if (!model) {
        setStatus("unavailable");
        return;
      }
      try {
        const started = await startWakeListener({
          modelUrl: model.url,
          onStatus: (s) => {
            console.info(`wake word: ${s}`);
            if (!cancelled) setStatus(s);
          },
          onWake: () => {
            console.info("wake word: heard");
            const active = listener.current;
            if (!active) return;
            callbacks.current.onWake(active.preroll());
            resumeSoon();
          },
          onConfirm: (decision) => {
            console.info(`voice approval: ${decision}`);
            callbacks.current.onConfirm(decision);
            resumeSoon();
          },
        });
        if (cancelled) {
          started.stop();
          return;
        }
        listener.current = started;
        started.setMode(modeRef.current); // start in the mode the app is in right now
      } catch (error) {
        console.error("wake word unavailable", error);
        if (!cancelled) setStatus("error");
      }
    })();
    // The listener turns itself off after a wake or a decision. If the app's mode did not
    // change meanwhile (e.g. it ignored the wake), switch back to it.
    const resumeSoon = () => window.setTimeout(() => listener.current?.setMode(modeRef.current), 1500);
    return () => {
      cancelled = true;
      listener.current?.stop();
      listener.current = null;
    };
  }, [enabled]);

  useEffect(() => {
    listener.current?.setMode(mode);
  }, [mode, status]);

  return status;
}
