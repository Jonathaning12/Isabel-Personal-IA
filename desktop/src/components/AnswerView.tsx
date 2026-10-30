import { useEffect, useState } from "react";
import { VAULT_PREFIX, isDesktop } from "../api";
import { Markdown } from "../lib/markdown";
import type { Message } from "../useAssistant";

const REVEAL_MS = 900;

/** The latest exchange, shown softly under the orb. The full history is in the sidebar. */
export function AnswerView({ messages, vaultName }: { messages: Message[]; vaultName?: string }) {
  const last = messages[messages.length - 1];
  const question = last?.role === "assistant" ? messages[messages.length - 2] : last;
  const answer = last?.role === "assistant" ? last : undefined;
  const [revealed, setRevealed] = useState(1);

  // Reveal a new answer progressively (a fade that follows the text).
  useEffect(() => {
    if (!answer) return;
    setRevealed(0);
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / REVEAL_MS);
      setRevealed(t);
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [answer]);

  if (!question && !answer) return null;
  const sources = answer?.citations?.filter((c) => new RegExp(`\\[${c.n}\\]`).test(answer.text)) ?? [];

  return (
    <section className="answer" aria-live="polite">
      {question?.role === "user" ? <p className="answer__question">{question.text}</p> : null}
      {answer ? (
        <div
          className="answer__body"
          style={{ maskImage: `linear-gradient(to bottom, #000 ${revealed * 100}%, transparent ${revealed * 100 + 25}%)` }}
        >
          <Markdown text={answer.text} citations={answer.citations} />
          {sources.length ? (
            <ul className="sources">
              {sources.map((c) => {
                // Notes from the Obsidian vault open in Obsidian with a click.
                const inVault = c.source_path.startsWith(VAULT_PREFIX) && Boolean(vaultName) && isDesktop();
                const open = () => void window.assistant?.openInObsidian(vaultName!, c.source_path.slice(VAULT_PREFIX.length));
                return (
                  <li key={c.n} title={inVault ? "Abrir en Obsidian" : c.text.slice(0, 300)} className={inVault ? "sources--link" : undefined}>
                    {inVault ? (
                      <button type="button" onClick={open}>
                        <span className="sources__n">{c.n}</span>
                        {c.title ?? c.source_path}
                      </button>
                    ) : (
                      <>
                        <span className="sources__n">{c.n}</span>
                        {c.title ?? c.source_path}
                      </>
                    )}
                    {c.heading && c.heading !== c.title ? <span className="sources__heading"> › {c.heading}</span> : null}
                    {c.suspicious ? <span className="sources__warn" title="Texto sospechoso: tratado solo como dato"> ⚠</span> : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
