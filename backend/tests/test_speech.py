"""AI voice for Ask answers: text cleanup, the /api/speech proxy to the gateway, and the browser fallback signals."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import speech

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 28


def test_clean_for_speech():
    t = speech.clean_for_speech("Photolysis splits **water** [S1]. It occurs in thylakoids [S2] → see https://x.org/a .")
    assert t == "Photolysis splits water. It occurs in thylakoids to see."
    long = "This is one sentence. " * 300
    out = speech.clean_for_speech(long)
    assert len(out) <= speech.MAX_SPEECH_CHARS and out.endswith(".")


@pytest.fixture
def ai_voice(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "use_mocks", False)
    monkeypatch.setattr(s, "tts_base_url", "https://gw.example/v1")
    monkeypatch.setattr(s, "tts_api_key", "lw-key")
    speech._cache.clear()
    calls = []

    class Resp:
        def __init__(self, status, content, ctype):
            self.status_code, self.content, self.headers, self.text = status, content, {"content-type": ctype}, content.decode("latin-1")

        def json(self):
            import json
            return json.loads(self.content)

    reply = {"value": Resp(200, WAV, "audio/wav")}

    async def fake_post(self, url, json=None, headers=None):
        calls.append({"url": url, "json": json, "headers": headers})
        if isinstance(reply["value"], Exception):
            raise reply["value"]
        return reply["value"]

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    yield TestClient(app), calls, reply, Resp
    speech._cache.clear()


def test_speech_returns_wav_from_the_gateway(ai_voice):
    c, calls, _, _ = ai_voice
    r = c.post("/api/speech", json={"text": "Photolysis splits water [S1]."})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == WAV
    sent = calls[0]
    assert sent["url"] == "https://gw.example/v1/audio/speech" and sent["headers"]["Authorization"] == "Bearer lw-key"
    assert sent["json"]["input"] == "Photolysis splits water." and sent["json"]["voice"] == "af_heart"


def test_replaying_an_answer_uses_the_cache(ai_voice):
    c, calls, _, _ = ai_voice
    c.post("/api/speech", json={"text": "Same answer [S1]."})
    c.post("/api/speech", json={"text": "Same answer [S2]."})  # same words once labels are removed
    assert len(calls) == 1


def test_gateway_errors_become_502(ai_voice):
    c, _, reply, Resp = ai_voice
    reply["value"] = Resp(503, b'{"error": {"message": "Voice model not loaded: OSError"}}', "application/json")
    r = c.post("/api/speech", json={"text": "Hello there."})
    assert r.status_code == 502 and "Voice model not loaded" in r.json()["error"]["message"]
    reply["value"] = httpx.ConnectError("tunnel down")
    assert c.post("/api/speech", json={"text": "Hello again."}).status_code == 502


def test_voice_off_is_501_so_the_browser_reads_it(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "use_mocks", False)
    monkeypatch.setattr(s, "tts_base_url", "")
    r = TestClient(app).post("/api/speech", json={"text": "Hello."})
    assert r.status_code == 501 and r.json()["error"]["code"] == "not_implemented"
    monkeypatch.setattr(s, "use_mocks", True)
    monkeypatch.setattr(s, "tts_base_url", "https://gw.example/v1")
    assert TestClient(app).post("/api/speech", json={"text": "Hello."}).status_code == 501  # mock mode: browser voice


def test_text_limits():
    c = TestClient(app)
    assert c.post("/api/speech", json={"text": ""}).status_code == 422
    assert c.post("/api/speech", json={"text": "x" * 6001}).status_code == 422


def test_citation_only_text_is_rejected(ai_voice):
    c, calls, _, _ = ai_voice
    r = c.post("/api/speech", json={"text": "[S1] [S2]"})
    assert r.status_code == 502 and not calls


def test_health_reports_voice_mode(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "use_mocks", True)
    assert TestClient(app).get("/api/health").json()["tts_mode"] == "browser"
