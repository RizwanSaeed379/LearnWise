from fastapi import APIRouter, Depends

from app.config import get_settings
from app.prompts import templates
from app.routers.common import retrieve_or_404
from app.schemas import NoteSection, NotesRequest, NotesResponse
from app.services import mock
from app.services.llm import LLMClient, get_llm

router = APIRouter(prefix="/api", tags=["notes"])


@router.post("/notes", response_model=NotesResponse, summary="Generate concise, detailed or exam notes")
async def notes(req: NotesRequest, llm: LLMClient = Depends(get_llm)):
    if get_settings().use_mocks:
        return NotesResponse(title=req.topic, style=req.style, sections=mock.notes(req.topic, req.style), sources=mock.sources(2))

    sources, context = retrieve_or_404(req.topic, req.document_ids, 8)
    data = await llm.chat_json(templates.notes_prompt(req.topic, req.style, context), max_tokens=2500)
    sections = [NoteSection(**s) for s in data.get("sections", []) if s.get("heading")]
    return NotesResponse(title=data.get("title", req.topic), style=req.style, sections=sections, sources=sources)
