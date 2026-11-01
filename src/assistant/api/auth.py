"""Local bearer token: every API route except /health needs `Authorization: Bearer <token>`.

The API only listens on 127.0.0.1, but any program on this computer could otherwise call
it (read memory, start actions). The token comes from API_TOKEN in .env or, if that is
empty, is generated once and saved to data/api_token, where the desktop app and the CLI
read it. The data/ folder never goes to git.
"""

import contextlib
import hmac
import logging
import os
import secrets
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from assistant.config import Settings

logger = logging.getLogger("assistant.auth")

TOKEN_FILE = "api_token"
OPEN_PATHS = {"/health"}  # Docker's healthcheck and the app's "is the API up?" probe


def load_or_create_token(settings: Settings) -> str:
    """The token the API requires ("" when REQUIRE_TOKEN=false, e.g. in unit tests)."""
    configured = settings.api_token.get_secret_value().strip()
    if configured or not settings.require_token:
        return configured
    path = Path(settings.data_dir) / TOKEN_FILE
    try:
        saved = path.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    with contextlib.suppress(OSError):  # best effort on Windows-mounted folders
        os.chmod(path, 0o600)  # only the owner can read it
    logger.info("api_token_created path=%s", path)
    return token


def client_token(settings: Settings) -> str:
    """The token for clients on this machine (CLI, scripts): .env first, then the file."""
    configured = settings.api_token.get_secret_value().strip()
    if configured:
        return configured
    try:
        return (Path(settings.data_dir) / TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


async def require_token(request: Request, call_next):
    """HTTP middleware: rejects requests without the right token (constant-time compare)."""
    token: str = getattr(request.app.state, "api_token", "")
    if token and request.url.path not in OPEN_PATHS:
        sent = request.headers.get("authorization", "")
        if not hmac.compare_digest(sent.encode(), f"Bearer {token}".encode()):
            return JSONResponse({"detail": "Missing or wrong API token"}, status_code=401)
    return await call_next(request)
