"""Split documents into chunks small enough to embed and to fit in a prompt.

Why chunk? One embedding per whole document blurs its meaning, and whole documents
do not fit in the model's context. Smaller chunks (~800 tokens) give precise search
hits. A small overlap keeps sentences that sit on a boundary from losing context.

Markdown is split by headings first, so each chunk remembers which section it came from.
"""

import re
from dataclasses import dataclass

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    heading: str | None


def _sections(text: str, markdown: bool) -> list[tuple[str | None, str]]:
    """Split text into (heading, body) sections. Non-markdown text is one section."""
    if not markdown:
        return [(None, text)]
    sections: list[tuple[str | None, str]] = []
    heading: str | None = None
    lines: list[str] = []
    for line in text.split("\n"):
        match = HEADING.match(line)
        if match:
            if "\n".join(lines).strip():
                sections.append((heading, "\n".join(lines)))
            heading, lines = match.group(2).strip(), []
        else:
            lines.append(line)
    if "\n".join(lines).strip():
        sections.append((heading, "\n".join(lines)))
    return sections


def _split_long(paragraph: str, max_chars: int, overlap: int) -> list[str]:
    """Hard-split a paragraph longer than max_chars, with overlap."""
    step = max(max_chars - overlap, 1)
    return [paragraph[i : i + max_chars] for i in range(0, len(paragraph), step)]


def _pack(body: str, max_chars: int, overlap: int) -> list[str]:
    """Greedily pack paragraphs into pieces of at most max_chars, with overlap."""
    paragraphs: list[str] = []
    for p in body.split("\n\n"):
        p = p.strip()
        if p:
            paragraphs.extend(_split_long(p, max_chars, overlap) if len(p) > max_chars else [p])

    pieces: list[str] = []
    current = ""
    for p in paragraphs:
        candidate = f"{current}\n\n{p}" if current else p
        if len(candidate) <= max_chars:
            current = candidate
            continue
        pieces.append(current)
        # Start the next piece with the tail of the previous one (overlap).
        tail = current[-overlap:] if overlap else ""
        current = f"{tail}\n\n{p}" if tail and len(tail) + len(p) + 2 <= max_chars else p
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, *, max_chars: int, overlap_chars: int, markdown: bool) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, body in _sections(text, markdown):
        for piece in _pack(body, max_chars, overlap_chars):
            chunks.append(Chunk(index=len(chunks), text=piece, heading=heading))
    return chunks
