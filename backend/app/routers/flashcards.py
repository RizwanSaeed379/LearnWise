import uuid

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.prompts import templates
from app.routers.common import retrieve_or_404, source_for_label
from app.schemas import Flashcard, FlashcardsRequest, FlashcardsResponse
from app.services import mock
from app.services.llm import LLMClient, get_llm
from app.services.validation import clean_cards

router = APIRouter(prefix="/api", tags=["flashcards"])


@router.post("/flashcards", response_model=FlashcardsResponse, summary="Generate flashcards for a topic")
async def flashcards(req: FlashcardsRequest, llm: LLMClient = Depends(get_llm)):
    if get_settings().use_mocks:
        return FlashcardsResponse(topic=req.topic, cards=mock.flashcards(req.topic, req.count))

    sources, context = retrieve_or_404(req.topic, req.document_ids, 8)
    data = await llm.chat_json(templates.flashcards_prompt(req.topic, req.count, context))
    cards = [
        Flashcard(card_id=f"card_{uuid.uuid4().hex[:8]}", front=c["front"], back=c["back"], topic=req.topic, source=source_for_label(c.get("source"), sources))
        for c in clean_cards(data.get("cards", []))
    ]
    return FlashcardsResponse(topic=req.topic, cards=cards)
