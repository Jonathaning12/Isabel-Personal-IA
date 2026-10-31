"""Voice: speech to text for commands, and natural text to speech for answers.

POST /transcribe takes a WAV file and returns {"text": ...}. The audio is sent to the
selected provider's chat model as an `input_audio` part (OpenAI-compatible format).
The transcript is NOT sent to the agent here: the app shows it and sends it to /chat.

POST /speak takes {"text", "voice"?} and returns a WAV with a natural Gemini voice
(text-to-speech through Gemini's native API). The text is an answer the model already
wrote, so nothing new leaves the machine.

/speak tries the chosen Gemini voice first, then the local Piper voice (services/voice,
LOCAL_VOICE_URL). /transcribe needs Gemini. Without an engine the endpoints answer 501
and the desktop app uses Windows' voices.

Free Gemini keys have a small daily TTS quota, so /speak saves every clip in
`data/tts_cache/` (repeated phrases cost nothing) and, after a 429, stops calling that
model until its retry time instead of making the app wait for an answer that won't come.
"""

import base64
import hashlib
import io
import logging
import re
import time
import wave
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from assistant.config import Settings

router = APIRouter()
logger = logging.getLogger("assistant.voice")

MAX_SPEAK_CHARS = 1500
# Prebuilt Gemini voices the app offers (Google's own one-word descriptions in comments).
VOICES = {"Achernar", "Sulafat", "Vindemiatrix", "Despina", "Aoede", "Kore", "Leda", "Charon"}
SPEAK_STYLE = "Say in Spanish, in a warm, soft and natural tone: "
QUOTA_PAUSE_S = 60.0  # used when a 429 does not say when to retry
MAX_CACHED_CLIPS = 300


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_SPEAK_CHARS)
    voice: str | None = Field(default=None, max_length=40)


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    """Gemini may return raw 16-bit mono PCM (audio/L16); browsers need a WAV header."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return buffer.getvalue()


def retry_after_s(reply: httpx.Response) -> float:
    """Seconds Gemini asks us to wait after a 429 (its RetryInfo detail), or a default."""
    found = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', reply.text)
    return float(found.group(1)) if found else QUOTA_PAUSE_S


def cache_file(cache_dir: Path, voice: str, text: str) -> Path:
    key = hashlib.sha256(f"{voice}|{SPEAK_STYLE}{text}".encode()).hexdigest()
    return cache_dir / f"{key}.wav"


def save_clip(path: Path, audio: bytes) -> None:
    """Store a clip and keep only the most recently used ones."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    clips = sorted(path.parent.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    for old in clips[:-MAX_CACHED_CLIPS]:
        old.unlink(missing_ok=True)


@router.post("/speak")
async def speak(request: Request, body: SpeakRequest) -> Response:
    """Speak with the chosen Gemini voice; if it is unavailable, with the local voice."""
    settings = request.app.state.settings
    if settings.llm_provider != "gemini" and not settings.local_voice_url:
        raise HTTPException(501, "Natural voice needs LLM_PROVIDER=gemini or LOCAL_VOICE_URL")
    voice = body.voice if body.voice in VOICES else settings.tts_voice
    cached = cache_file(Path(settings.data_dir) / "tts_cache", voice, body.text)
    if cached.exists():
        cached.touch()  # recently used: keep it
        logger.info("tts cache_hit voice=%s chars=%d", voice, len(body.text))
        return wav_response(cached.read_bytes(), "gemini")
    if settings.llm_provider == "gemini":
        audio = await gemini_speech(request, voice, body.text)
        if audio:
            save_clip(cached, audio)
            return wav_response(audio, "gemini")
    audio = await local_speech(settings, body.text)
    if audio:
        return wav_response(audio, "local")
    raise HTTPException(503, "tts_unavailable")


def wav_response(audio: bytes, engine: str) -> Response:
    # X-Voice-Engine tells the app (and the logs) which voice was used.
    return Response(content=audio, media_type="audio/wav", headers={"X-Voice-Engine": engine})


async def gemini_speech(request: Request, voice: str, text: str) -> bytes | None:
    settings = request.app.state.settings
    payload = {
        "contents": [{"parts": [{"text": SPEAK_STYLE + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    # Model -> time.monotonic() until which its quota is exhausted (set after a 429).
    if not hasattr(request.app.state, "tts_paused"):
        request.app.state.tts_paused = {}
    paused: dict[str, float] = request.app.state.tts_paused
    # The TTS models are often saturated: each one gets a short time limit, and if the main
    # model is slow or busy the backup model is tried right away (same voice).
    models = [m for m in (settings.tts_model, settings.tts_fallback_model) if m]
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=settings.tts_attempt_timeout_s) as client:
        for model in models:
            if paused.get(model, 0.0) > time.monotonic():
                continue
            url = f"{settings.gemini_native_url}/models/{model}:generateContent"
            try:
                reply = await client.post(
                    url, headers={"x-goog-api-key": settings.inference_api_key}, json=payload
                )
                if reply.status_code == 429:
                    wait = retry_after_s(reply)
                    paused[model] = time.monotonic() + wait
                    logger.warning("tts_quota_exhausted model=%s pause_s=%d", model, wait)
                    continue
                reply.raise_for_status()
                part = reply.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                audio = base64.b64decode(part["data"], validate=True)
                mime = part.get("mimeType", "")
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                logger.warning("tts_failed model=%s error=%s", model, type(exc).__name__)
                continue
            if "wav" not in mime:
                rate = re.search(r"rate=(\d+)", mime)
                audio = pcm_to_wav(audio, int(rate.group(1)) if rate else 24000)
            logger.info(
                "tts model=%s voice=%s chars=%d latency_ms=%d",
                model,
                voice,
                len(text),
                (time.perf_counter() - start) * 1000,
            )
            return audio
    return None


async def local_speech(settings: Settings, text: str) -> bytes | None:
    """The local Piper voice (services/voice): no quota, nothing leaves the machine."""
    if not settings.local_voice_url:
        return None
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.local_voice_timeout_s) as client:
            reply = await client.post(f"{settings.local_voice_url}/tts", json={"text": text})
            reply.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("tts_failed model=local error=%s", type(exc).__name__)
        return None
    logger.info(
        "tts model=local chars=%d latency_ms=%d", len(text), (time.perf_counter() - start) * 1000
    )
    return reply.content


MAX_AUDIO_MB = 10
TRANSCRIBE_PROMPT = (
    "Transcribe this audio verbatim, in the language it is spoken. "
    "Return only the transcription, with no comments. If there is no speech, return nothing."
)


@router.post("/transcribe")
async def transcribe(request: Request, audio: UploadFile) -> dict[str, str]:
    state = request.app.state
    if state.settings.llm_provider != "gemini":
        raise HTTPException(501, "Voice input needs LLM_PROVIDER=gemini")

    max_bytes = MAX_AUDIO_MB * 1024 * 1024
    data = await audio.read(max_bytes + 1)
    if not data:
        raise HTTPException(400, "Empty audio")
    if len(data) > max_bytes:
        raise HTTPException(413, f"Audio larger than {MAX_AUDIO_MB} MB")

    message = await state.chat.complete(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": TRANSCRIBE_PROMPT},
                    {
                        "type": "input_audio",
                        "input_audio": {"data": base64.b64encode(data).decode(), "format": "wav"},
                    },
                ],
            }
        ],
        thinking=False,
        max_tokens=1000,
    )
    return {"text": (message.content or "").strip()}
