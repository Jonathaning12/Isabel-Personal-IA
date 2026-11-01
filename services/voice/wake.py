"""Trained wake word ("Isabel") with openWakeWord, for the voice service.

The desktop app streams the microphone (16 kHz, 16-bit mono) over a local WebSocket while
it waits for the name; every 80 ms chunk is scored by a small model trained for that one
word, on top of openWakeWord's shared speech features. A score above the threshold sends
{"detected": true} back. Nothing is stored and nothing leaves the machine.

The model is the user's own file (data/wakeword/isabel.onnx, see services/voice/TRAINING.md).
Without it the endpoint reports unavailable and the app keeps its Vosk detector.
"""

import json
import os
import time
from pathlib import Path

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

FEATURES = Path(os.environ.get("OWW_FEATURES_DIR", "/models/oww"))
MODEL = Path(os.environ.get("WAKEWORD_MODEL", "/wakeword/isabel.onnx"))
THRESHOLD = float(os.environ.get("WAKEWORD_THRESHOLD", "0.5"))
CHUNK = 1280  # 80 ms at 16 kHz, what openWakeWord expects
COOLDOWN_S = 2.0


def available() -> bool:
    return MODEL.is_file()


def new_detector():
    """One detector per connection: it keeps its own audio and feature buffers."""
    from openwakeword.model import Model  # imported lazily: only needed with a model

    return Model(
        wakeword_models=[str(MODEL)],
        inference_framework="onnx",
        melspec_model_path=str(FEATURES / "melspectrogram.onnx"),
        embedding_model_path=str(FEATURES / "embedding_model.onnx"),
    )


def status() -> dict:
    return {"available": available(), "model": MODEL.name if available() else None, "threshold": THRESHOLD}


async def stream(websocket: WebSocket) -> None:
    await websocket.accept()
    if not available():
        await websocket.send_text(json.dumps({"error": "no trained model"}))
        await websocket.close()
        return
    detector = new_detector()
    pending = np.zeros(0, dtype=np.int16)
    last = 0.0
    try:
        while True:
            data = await websocket.receive_bytes()
            pending = np.concatenate([pending, np.frombuffer(data, dtype="<i2")])
            while len(pending) >= CHUNK:
                chunk, pending = pending[:CHUNK], pending[CHUNK:]
                score = max(detector.predict(chunk).values())
                now = time.monotonic()
                if score >= THRESHOLD and now - last > COOLDOWN_S:
                    last = now
                    detector.reset()  # start fresh: the same word must not fire twice
                    await websocket.send_text(json.dumps({"detected": True, "score": round(float(score), 3)}))
    except WebSocketDisconnect:
        return
