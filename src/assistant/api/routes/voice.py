"""Voice: speech to text for commands, and natural text to speech for answers.

POST /transcribe takes a WAV file and returns {"text": ...}. The audio is sent to the
selected provider's chat model as an `input_audio` part (OpenAI-compatible format).
The transcript is NOT sent to the agent here: the app shows it and sends it to /chat.

POST /speak takes {"text", "voice"?} and returns a WAV with a natural Gemini voice
(text-to-speech through Gemini's native API). The text is an answer the model already
wrote, so nothing new leaves the machine.

Only Gemini offers audio today; with Nebius both endpoints answer 501 and the desktop app
falls back to the operating system's voices.
"""

import base64
import io
import logging
import re
import time
import wave

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger("assistant.voice")

MAX_SPEAK_CHARS = 1500
# Prebuilt Gemini voices the app offers (Google's own one-word descriptions in comments).
VOICES = {"Achernar", "Sulafat", "Vindemiatrix", "Despina", "Aoede", "Kore", "Leda", "Charon"}
SPEAK_STYLE = "Say in Spanish, in a warm, soft and natural tone: "


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


@router.post("/speak")
async def speak(request: Request, body: SpeakRequest) -> Response:
    settings = request.app.state.settings
    if settings.llm_provider != "gemini":
        raise HTTPException(501, "Natural voice needs LLM_PROVIDER=gemini")
    voice = body.voice if body.voice in VOICES else settings.tts_voice
    payload = {
        "contents": [{"parts": [{"text": SPEAK_STYLE + body.text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    # The TTS models are often saturated: each one gets a short time limit, and if the main
    # model is slow or busy the backup model is tried right away (same voice).
    models = [m for m in (settings.tts_model, settings.tts_fallback_model) if m]
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=settings.tts_attempt_timeout_s) as client:
        for model in models:
            url = f"{settings.gemini_native_url}/models/{model}:generateContent"
            try:
                reply = await client.post(
                    url, headers={"x-goog-api-key": settings.inference_api_key}, json=payload
                )
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
                len(body.text),
                (time.perf_counter() - start) * 1000,
            )
            return Response(content=audio, media_type="audio/wav")
    raise HTTPException(503, "tts_unavailable")


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
