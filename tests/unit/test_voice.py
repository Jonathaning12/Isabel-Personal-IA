"""Unit tests for POST /transcribe, with the provider's chat endpoint mocked."""

import base64
import json

import httpx
import respx
from pydantic import SecretStr

from tests.conftest import FAKE_BASE_URL
from tests.unit.test_health import make_client
from tests.unit.test_llm import chat_response

CHAT_URL = f"{FAKE_BASE_URL}chat/completions"
WAV = b"RIFF....WAVEfmt fake audio"


def gemini(settings):
    return settings.model_copy(
        update={
            "llm_provider": "gemini",
            "gemini_api_key": SecretStr("gemini-key"),
            "gemini_base_url": FAKE_BASE_URL,
        }
    )


@respx.mock
def test_transcribe_sends_audio_and_returns_text(monkeypatch, settings, tmp_path):
    route = respx.post(CHAT_URL).mock(return_value=chat_response("  hola asistente \n"))

    with make_client(monkeypatch, gemini(settings), tmp_path) as client:
        response = client.post("/transcribe", files={"audio": ("voz.wav", WAV, "audio/wav")})

    assert response.status_code == 200
    assert response.json() == {"text": "hola asistente"}
    content = json.loads(route.calls.last.request.content)["messages"][0]["content"]
    audio = next(part for part in content if part["type"] == "input_audio")["input_audio"]
    assert audio["format"] == "wav"
    assert base64.b64decode(audio["data"]) == WAV


def test_transcribe_is_unavailable_with_nebius(monkeypatch, settings, tmp_path):
    with make_client(monkeypatch, settings, tmp_path) as client:
        response = client.post("/transcribe", files={"audio": ("voz.wav", WAV, "audio/wav")})

    assert response.status_code == 501


TTS_URL = "https://tts.test/v1beta/models/test-tts:generateContent"


def tts_settings(settings):
    return gemini(settings).model_copy(
        update={"gemini_native_url": "https://tts.test/v1beta", "tts_model": "test-tts"}
    )


@respx.mock
def test_speak_returns_wav_with_the_chosen_voice(monkeypatch, settings, tmp_path):
    pcm = b"\x01\x00" * 100
    route = respx.post(TTS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/L16;codec=pcm;rate=24000",
                                        "data": base64.b64encode(pcm).decode(),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )
    )

    with make_client(monkeypatch, tts_settings(settings), tmp_path) as client:
        response = client.post("/speak", json={"text": "Hola", "voice": "Sulafat"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF" and response.content.endswith(pcm)
    sent = json.loads(route.calls.last.request.content)
    voice = sent["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]
    assert voice["voiceName"] == "Sulafat"
    assert route.calls.last.request.headers["x-goog-api-key"] == "gemini-key"


BACKUP_URL = "https://tts.test/v1beta/models/backup-tts:generateContent"


def wav_reply() -> httpx.Response:
    data = base64.b64encode(b"RIFF....WAVE").decode()
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"inlineData": {"mimeType": "audio/wav", "data": data}}]}}
            ]
        },
    )


@respx.mock
def test_speak_uses_the_backup_model_when_the_main_one_is_busy(monkeypatch, settings, tmp_path):
    main = respx.post(TTS_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    backup = respx.post(BACKUP_URL).mock(return_value=wav_reply())
    configured = tts_settings(settings).model_copy(update={"tts_fallback_model": "backup-tts"})

    with make_client(monkeypatch, configured, tmp_path) as client:
        response = client.post("/speak", json={"text": "Hola"})

    assert response.status_code == 200 and response.content.startswith(b"RIFF")
    assert main.called and backup.called


@respx.mock
def test_speak_failure_is_a_clean_503(monkeypatch, settings, tmp_path):
    respx.post(TTS_URL).mock(return_value=httpx.Response(503, json={"error": "busy"}))
    respx.post(BACKUP_URL).mock(return_value=httpx.Response(503, json={"error": "busy"}))
    configured = tts_settings(settings).model_copy(update={"tts_fallback_model": "backup-tts"})

    with make_client(monkeypatch, configured, tmp_path) as client:
        response = client.post("/speak", json={"text": "Hola"})

    assert response.status_code == 503


def test_speak_is_unavailable_with_nebius(monkeypatch, settings, tmp_path):
    with make_client(monkeypatch, settings, tmp_path) as client:
        assert client.post("/speak", json={"text": "Hola"}).status_code == 501


def test_transcribe_rejects_empty_audio(monkeypatch, settings, tmp_path):
    with make_client(monkeypatch, gemini(settings), tmp_path) as client:
        response = client.post("/transcribe", files={"audio": ("voz.wav", b"", "audio/wav")})

    assert response.status_code == 400


@respx.mock
def test_speak_reuses_a_cached_clip(monkeypatch, settings, tmp_path):
    route = respx.post(TTS_URL).mock(return_value=wav_reply())

    with make_client(monkeypatch, tts_settings(settings), tmp_path) as client:
        first = client.post("/speak", json={"text": "Necesito tu aprobación"})
        second = client.post("/speak", json={"text": "Necesito tu aprobación"})

    assert first.status_code == second.status_code == 200
    assert second.content == first.content
    assert route.call_count == 1


@respx.mock
def test_speak_pauses_a_model_whose_quota_is_exhausted(monkeypatch, settings, tmp_path):
    quota = httpx.Response(
        429, json={"error": {"details": [{"retryDelay": "40s"}]}, "status": "RESOURCE_EXHAUSTED"}
    )
    main = respx.post(TTS_URL).mock(return_value=quota)
    backup = respx.post(BACKUP_URL).mock(return_value=wav_reply())
    configured = tts_settings(settings).model_copy(update={"tts_fallback_model": "backup-tts"})

    with make_client(monkeypatch, configured, tmp_path) as client:
        assert client.post("/speak", json={"text": "Uno"}).status_code == 200
        assert client.post("/speak", json={"text": "Dos"}).status_code == 200

    assert main.call_count == 1  # not called again during the pause
    assert backup.call_count == 2


LOCAL = "http://voice.test"


@respx.mock
def test_speak_uses_the_local_voice_when_gemini_is_out_of_quota(monkeypatch, settings, tmp_path):
    respx.post(TTS_URL).mock(return_value=httpx.Response(429, json={"error": "quota"}))
    local = respx.post(f"{LOCAL}/tts").mock(return_value=httpx.Response(200, content=b"RIFF-local"))
    configured = tts_settings(settings).model_copy(
        update={"local_voice_url": LOCAL, "tts_fallback_model": ""}
    )

    with make_client(monkeypatch, configured, tmp_path) as client:
        response = client.post("/speak", json={"text": "Hola"})

    assert response.status_code == 200 and response.content == b"RIFF-local"
    assert response.headers["x-voice-engine"] == "local"
    assert json.loads(local.calls.last.request.content) == {"text": "Hola"}


@respx.mock
def test_local_voice_works_without_gemini(monkeypatch, settings, tmp_path):
    respx.post(f"{LOCAL}/tts").mock(return_value=httpx.Response(200, content=b"RIFF-local"))
    configured = settings.model_copy(update={"local_voice_url": LOCAL})

    with make_client(monkeypatch, configured, tmp_path) as client:
        assert client.post("/speak", json={"text": "Hola"}).content == b"RIFF-local"
