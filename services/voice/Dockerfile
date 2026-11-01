# Local voice service: Piper text to speech and the openWakeWord wake word, CPU only.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps openwakeword==0.6.0

# The voice is downloaded once, at build time; at runtime the service needs no internet.
# Default: "claude", a Mexican Spanish female voice, high quality (~63 MB). Any voice from
# https://huggingface.co/rhasspy/piper-voices works: set PIPER_VOICE to its path.
ARG PIPER_VOICE=es/es_MX/claude/high/es_MX-claude-high
ADD https://huggingface.co/rhasspy/piper-voices/resolve/main/${PIPER_VOICE}.onnx /models/voice.onnx
ADD https://huggingface.co/rhasspy/piper-voices/resolve/main/${PIPER_VOICE}.onnx.json /models/voice.onnx.json

# openWakeWord's shared feature models (Apache-2.0); the "Isabel" model itself is the
# user's file in data/wakeword/ (see TRAINING.md).
ADD https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.onnx /models/oww/
ADD https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.onnx /models/oww/

COPY app.py wake.py ./
RUN useradd --uid 10002 --create-home speech && chmod -R a+rX /models
USER speech

EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
