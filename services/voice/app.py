"""Local voice service: text to speech with Piper, and the trained wake word, on the CPU.

It runs in its own container; the API reaches it at http://voice:8100 and the desktop app
at 127.0.0.1:8100 (published on this machine only). The models are inside the image (or
in data/wakeword/), so no text or audio leaves the machine and there is no quota. The API
uses the voice when the chosen Gemini voice is unavailable (free-tier quota exhausted,
provider busy, or no Gemini at all).

POST /tts          {"text": ..., "speed"?: ...}  -> audio/wav
GET  /wake/status  is a trained wake-word model installed?
WS   /wake         16 kHz 16-bit mono audio in, {"detected": true} out (see wake.py)
GET  /health
"""

import io
import os
import threading
import wave
from contextlib import asynccontextmanager

import wake
from fastapi import FastAPI, HTTPException, Response, WebSocket
from piper import PiperVoice, SynthesisConfig
from pydantic import BaseModel, Field

MODEL = os.environ.get("LOCAL_TTS_MODEL", "/models/voice.onnx")
# Piper's "length scale": above 1 speaks slower, below 1 faster.
SPEED = float(os.environ.get("LOCAL_TTS_SPEED", "1.0"))

voices: dict[str, PiperVoice] = {}
# One synthesis at a time keeps CPU and memory use predictable on a laptop.
busy = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    voices["main"] = PiperVoice.load(MODEL)
    yield
    voices.clear()


app = FastAPI(title="Local voice", lifespan=lifespan)


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    speed: float | None = Field(default=None, ge=0.5, le=2.0)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok" if voices else "loading"}


@app.post("/tts")
def tts(body: TtsRequest) -> Response:
    voice = voices.get("main")
    if voice is None:
        raise HTTPException(503, "loading")
    speed = body.speed or SPEED
    config = SynthesisConfig(length_scale=None if speed == 1.0 else 1.0 / speed)
    buffer = io.BytesIO()
    with busy, wave.open(buffer, "wb") as out:
        voice.synthesize_wav(body.text, out, syn_config=config)
    return Response(content=buffer.getvalue(), media_type="audio/wav")


@app.get("/wake/status")
def wake_status() -> dict:
    return wake.status()


@app.websocket("/wake")
async def wake_stream(websocket: WebSocket) -> None:
    await wake.stream(websocket)
