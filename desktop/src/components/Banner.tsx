import { useEffect, useRef, useState } from "react";
import type { Phase } from "../useAssistant";
import { MicIcon, SendIcon, StopIcon, TextIcon } from "./Icons";

interface Props {
  phase: Phase;
  busy: boolean;
  onSend: (text: string) => void;
  onToggleMic: () => void;
  /** True while a dialog (the approval card) owns the keyboard. */
  locked?: boolean;
}

/** The small control strip under the orb: microphone and text input. */
export function Banner({ phase, busy, onSend, onToggleMic, locked = false }: Props) {
  const [typing, setTyping] = useState(false);
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const listening = phase === "listening";

  useEffect(() => {
    if (typing) input.current?.focus();
  }, [typing]);

  // "/" or any letter key opens the text field, like a command palette.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (locked || typing || target.closest("input, textarea, select, [contenteditable]")) return;
      if (event.key === "/" || (event.key.length === 1 && /\p{L}/u.test(event.key) && !event.ctrlKey && !event.metaKey)) {
        setTyping(true);
        if (event.key !== "/") setText(event.key);
        event.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [typing, locked]);

  const submit = () => {
    if (!text.trim() || busy) return;
    onSend(text);
    setText("");
  };

  return (
    <div className={`banner ${typing ? "banner--typing" : ""}`}>
      <button
        type="button"
        className={`round-button ${listening ? "round-button--live" : ""}`}
        onClick={onToggleMic}
        disabled={busy && !listening}
        aria-label={listening ? "Detener grabación" : "Hablar con el asistente"}
        title={listening ? "Detener" : "Hablar"}
      >
        {listening ? <StopIcon /> : <MicIcon />}
      </button>

      <div className="banner__field">
        {typing ? (
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <input
              ref={input}
              value={text}
              maxLength={8000}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setTyping(false);
                  setText("");
                }
              }}
              placeholder={busy ? "Espera un momento…" : "Escribe y pulsa Enter"}
              aria-label="Mensaje para el asistente"
            />
            <button type="submit" className="composer__send" disabled={!text.trim() || busy} aria-label="Enviar">
              <SendIcon />
            </button>
          </form>
        ) : null}
      </div>

      <button
        type="button"
        className={`round-button ${typing ? "round-button--active" : ""}`}
        onClick={() => setTyping((t) => !t)}
        aria-label={typing ? "Cerrar el campo de texto" : "Escribir al asistente"}
        title={typing ? "Cerrar" : "Escribir"}
      >
        <TextIcon />
      </button>
    </div>
  );
}
