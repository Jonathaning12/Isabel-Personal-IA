"""Append-only audit log of every side-effect decision (approve / reject).

One JSON object per line in data/audit.log. Arguments are stored as a SHA-256
hash, so the log proves *what* was approved without copying personal data.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self, *, thread_id: str, tool: str, args: dict[str, Any], decision: str, summary: str
    ) -> None:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "thread_id": thread_id,
            "tool": tool,
            "args_sha256": hashlib.sha256(
                json.dumps(args, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
            "decision": decision,
            "result": summary,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
