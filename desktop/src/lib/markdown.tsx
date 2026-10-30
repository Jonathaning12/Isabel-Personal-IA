// Minimal, safe Markdown for answers: paragraphs, bullet/numbered lists, **bold**,
// `code`, code blocks and [n] citations. It builds React nodes (never raw HTML), so
// text coming from the model or from notes cannot inject markup.

import { Fragment, type ReactNode } from "react";
import type { Citation } from "../api";

function inline(text: string, citations: Citation[], key: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g);
  return parts.map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={k}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={k}>{part.slice(1, -1)}</code>;
    const cite = /^\[(\d+)\]$/.exec(part);
    if (cite) {
      const n = Number(cite[1]);
      const source = citations.find((c) => c.n === n);
      const title = source ? `${source.source_path}${source.heading ? ` › ${source.heading}` : ""}` : undefined;
      return (
        <sup key={k} className="cite" title={title}>
          {n}
        </sup>
      );
    }
    return <Fragment key={k}>{part}</Fragment>;
  });
}

export function Markdown({ text, citations = [] }: { text: string; citations?: Citation[] }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let list: { ordered: boolean; items: string[] } | null = null;
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length) {
      const key = `p${blocks.length}`;
      blocks.push(<p key={key}>{inline(paragraph.join(" "), citations, key)}</p>);
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      const key = `l${blocks.length}`;
      const items = list.items.map((item, i) => <li key={i}>{inline(item, citations, `${key}-${i}`)}</li>);
      blocks.push(list.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>);
      list = null;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      flushParagraph();
      flushList();
      const code: string[] = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith("```"); i++) code.push(lines[i]);
      blocks.push(
        <pre key={`c${blocks.length}`}>
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const ordered = Boolean(numbered);
      if (list && list.ordered !== ordered) flushList();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    flushList();
    paragraph.push(line.replace(/^#+\s*/, ""));
  }
  flushParagraph();
  flushList();
  return <>{blocks}</>;
}
