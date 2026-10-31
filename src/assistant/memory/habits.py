"""Habits Isabel learns by watching, not by being told (stored in data/habits.json).

Today: what music the user plays. Every song or artist that really started playing
(spotify_play with status "ok") is logged with its time; the agent's prompt gets the top
artists of the last weeks, so "pon música" with no artist can pick something the user
likes. Counting is plain statistics (no LLM). The file stays on this machine, and
`DELETE /habits` wipes it.
"""

import json
import threading
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

MAX_EVENTS = 1000
WINDOW_DAYS = 60


class HabitLog:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"music": []}
        return (
            data
            if isinstance(data, dict) and isinstance(data.get("music"), list)
            else {"music": []}
        )

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(self._path)

    def record_music(self, artist: str, title: str = "", at: datetime | None = None) -> None:
        artist = artist.strip()[:100]
        if not artist:
            return
        event = {
            "artist": artist,
            "title": title.strip()[:150],
            "at": (at or datetime.now(UTC)).isoformat(),
        }
        with self._lock:
            data = self._load()
            data["music"] = [*data["music"], event][-MAX_EVENTS:]
            self._save(data)

    def top_artists(self, limit: int = 5, now: datetime | None = None) -> list[tuple[str, int]]:
        since = (now or datetime.now(UTC)) - timedelta(days=WINDOW_DAYS)
        names: dict[str, str] = {}  # lowercase -> how it was written last
        counts: Counter[str] = Counter()
        for event in self._load()["music"]:
            try:
                when = datetime.fromisoformat(event["at"])
            except (KeyError, TypeError, ValueError):
                continue
            if when >= since and event.get("artist"):
                key = event["artist"].casefold()
                names[key] = event["artist"]
                counts[key] += 1
        return [(names[key], n) for key, n in counts.most_common(limit)]

    def describe(self) -> list[str]:
        """Short lines for the agent's prompt (empty when nothing has been learned yet)."""
        top = self.top_artists()
        if not top:
            return []
        artists = ", ".join(f"{name} ({n})" for name, n in top)
        return [f"Most played artists, last {WINDOW_DAYS} days (plays): {artists}."]

    def clear(self) -> None:
        with self._lock:
            self._save({"music": []})


def artist_from_play(args: dict[str, Any], result: dict[str, Any]) -> tuple[str, str]:
    """(artist, title) of a successful spotify_play, from its arguments and result.

    For a track the result says "Song — Artist"; for an artist, the query is the artist.
    Playlists and albums without an artist are not counted.
    """
    kind = args.get("kind", "track")
    artist = str(args.get("artist") or "")
    playing = str(result.get("playing") or "")
    if kind == "artist":
        return str(args.get("query") or playing), ""
    if kind == "track" and " — " in playing:
        title, _, artists = playing.partition(" — ")
        return artist or artists.split(",")[0], title
    return artist, playing
