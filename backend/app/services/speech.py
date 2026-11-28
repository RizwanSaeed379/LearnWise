"""Text-to-speech for Ask answers: calls the gateway's OpenAI-style POST {TTS_BASE_URL}/audio/speech (Kokoro on
Kaggle) and returns WAV bytes. The browser's own voice is the fallback, handled in the frontend."""
from __future__ import annotations

import re
from collections import OrderedDict

import httpx

from app.config import get_settings

MAX_SPEECH_CHARS = 3500  # the gateway accepts 4000; a few-sentence answer is ~500
_CITE = re.compile(r"\s*\[S\d+\]")
_MD = re.compile(r"[*_`#>]+")
_URL = re.compile(r"https?://\S+")
_cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()  # replaying an answer doesn't regenerate it
_CACHE_SIZE = 32


class SpeechError(RuntimeError):
    pass


def clean_for_speech(text: str) -> str:
    """What a listener should hear: no [S1] labels, markdown symbols or links; arrows read as words."""
    t = _CITE.sub("", str(text))
    t = _URL.sub("", t)
    t = _MD.sub("", t)
    t = t.replace("→", " to ").replace("->", " to ").replace("…", ".")
    t = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s+", " ", t)).strip()
    if len(t) > MAX_SPEECH_CHARS:
        cut = t[:MAX_SPEECH_CHARS]
        t = cut[: cut.rfind(". ") + 1] or cut  # end on a full sentence
    return t


async def synthesize(text: str, voice: str | None = None) -> bytes:
    s = get_settings()
    clean = clean_for_speech(text)
    if not clean:
        raise SpeechError("Nothing to read aloud.")
    voice = voice or s.tts_voice
    key = (voice, clean)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    url = f"{s.tts_base_url.rstrip('/')}/audio/speech"
    try:
        async with httpx.AsyncClient(timeout=s.tts_timeout_seconds) as client:
            r = await client.post(url, json={"model": s.tts_model, "input": clean, "voice": voice, "response_format": "wav"},
                                  headers={"Authorization": f"Bearer {s.tts_api_key}", "ngrok-skip-browser-warning": "true"})
    except httpx.HTTPError as e:
        raise SpeechError(f"Voice request to {s.tts_base_url} failed: {e}") from e
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("audio/"):
        try:
            detail = r.json()["error"]["message"]
        except Exception:
            detail = r.text[:200]
        raise SpeechError(f"Voice server answered {r.status_code}: {detail}")
    _cache[key] = r.content
    while len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return r.content
