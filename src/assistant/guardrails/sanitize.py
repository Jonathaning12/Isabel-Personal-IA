"""Text normalization and prompt-injection heuristics.

Ingested documents are untrusted data. We normalize their text and flag chunks
that look like instructions aimed at the model ("ignore previous instructions").
Flagged chunks are still stored and searchable, but they are labeled as
suspicious in the prompt and can never trigger actions on their own.
"""

import re
import unicodedata

ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
# Control characters except tab (\t) and newline (\n).
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MANY_BLANK_LINES = re.compile(r"\n{3,}")

SUSPICIOUS_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions",
        r"ignora\s+(todas\s+)?las\s+instrucciones\s+(anteriores|previas)",
        r"system\s+prompt",
        r"you\s+are\s+now\b",
        r"run_code_in_sandbox|remember_fact|forget_fact",
        r"rm\s+-rf",
    )
]


def normalize_text(text: str) -> str:
    """Unicode NFKC, drop zero-width/control chars, unify newlines, trim blank runs."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = ZERO_WIDTH.sub("", text)
    text = CONTROL.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = MANY_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def is_suspicious(text: str) -> bool:
    """True if the text contains instruction-like patterns aimed at the model."""
    return any(p.search(text) for p in SUSPICIOUS_PATTERNS)
