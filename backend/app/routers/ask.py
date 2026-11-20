from fastapi import APIRouter, Depends

from app.config import get_settings
from app.prompts import templates
from app.routers.common import retrieve_or_404
from app.schemas import AskRequest, AskResponse
from app.services import mock
from app.services.llm import LLMClient, get_llm

router = APIRouter(prefix="/api", tags=["ask"])


@router.post("/ask", response_model=AskResponse, summary="Ask a question about your material (RAG)")
async def ask(req: AskRequest, llm: LLMClient = Depends(get_llm)):
    if get_settings().use_mocks:
        return AskResponse(answer=mock.answer(req.question), sources=mock.sources(2), grounded=True)

    sources, context = retrieve_or_404(req.question, req.document_ids, req.top_k)
    text = await llm.chat(templates.ask_prompt(req.question, context))
    if "NOT_FOUND" in text:
        return AskResponse(answer="I couldn't find this in your uploaded material.", sources=[], grounded=False)
    return AskResponse(answer=text, sources=sources, grounded=True)
