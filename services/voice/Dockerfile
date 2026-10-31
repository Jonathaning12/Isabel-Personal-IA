# Local voice service: Piper text to speech, CPU only.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The voice is downloaded once, at build time; at runtime the service needs no internet.
# Default: "claude", a Mexican Spanish female voice, high quality (~63 MB). Any voice from
# https://huggingface.co/rhasspy/piper-voices works: set PIPER_VOICE to its path.
ARG PIPER_VOICE=es/es_MX/claude/high/es_MX-claude-high
ADD https://huggingface.co/rhasspy/piper-voices/resolve/main/${PIPER_VOICE}.onnx /models/voice.onnx
ADD https://huggingface.co/rhasspy/piper-voices/resolve/main/${PIPER_VOICE}.onnx.json /models/voice.onnx.json

COPY app.py .
RUN useradd --uid 10002 --create-home speech && chmod -R a+rX /models
USER speech

EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
