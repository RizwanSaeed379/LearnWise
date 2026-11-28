from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.config import get_settings
from app.schemas import SpeechRequest
from app.services import speech

router = APIRouter(prefix="/api", tags=["voice"])


@router.post(
    "/speech",
    summary="Read text aloud with the AI voice (WAV audio)",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}, "description": "WAV audio, 24 kHz mono"},
               501: {"description": "AI voice is off (mock mode or no TTS_BASE_URL): use the browser's voice"},
               502: {"description": "The voice server failed: use the browser's voice"}},
)
async def speak(req: SpeechRequest):
    s = get_settings()
    if s.use_mocks or not s.tts_base_url.strip():
        raise HTTPException(501, detail="AI voice is off (set TTS_BASE_URL from the Kaggle notebook). Use the browser's voice.")
    try:
        audio = await speech.synthesize(req.text, req.voice)
    except speech.SpeechError as e:
        raise HTTPException(502, detail=str(e))
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})
