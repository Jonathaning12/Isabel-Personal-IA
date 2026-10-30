"""The user's current date and time, as a sentence for the system prompt.

The API runs in a Docker container whose clock is UTC, and the sandbox has no idea where
the user lives. So each client (desktop app, CLI) sends its local time with its UTC offset,
and the agent answers "what time is it?" from that, without running any code.
"""

from datetime import UTC, datetime

WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip


def _offset(moment: datetime) -> str:
    delta = moment.utcoffset()
    if delta is None:
        return "UTC"
    minutes = int(delta.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{mins:02d}"


def describe_now(local_time: str | None, timezone: str | None) -> str:
    """E.g. 'jueves 30 de octubre de 2026, 14:05 (America/Mexico_City, UTC-06:00)'.

    `local_time` is the client's ISO 8601 time with offset. Without a valid one, the
    server's UTC time is used and the sentence says the user's time zone is unknown.
    """
    moment = None
    if local_time:
        try:
            moment = datetime.fromisoformat(local_time)
        except ValueError:
            moment = None
    if moment is None or moment.utcoffset() is None:
        moment = datetime.now(UTC)
        zone = "UTC; the user's time zone is unknown"
    else:
        zone = f"{timezone}, {_offset(moment)}" if timezone else _offset(moment)
    date = (
        f"{WEEKDAYS[moment.weekday()]} {moment.day} de {MONTHS[moment.month - 1]} de {moment.year}"
    )
    return f"{date}, {moment:%H:%M} ({zone})"
